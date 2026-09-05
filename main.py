import flet as ft
import json
import os
import requests
import threading
import time
from datetime import datetime, timedelta
from database import SupabaseManager
from components import LectureCard, TopicCard, CommentCard

EMPTY = ft.Container(visible=False)
PRIMARY = ft.colors.INDIGO_400
BLUE = ft.colors.BLUE_700
DONE = ft.colors.TEAL_400

class ForumApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.rtl = True

        # قفل لحماية تحديثات الصفحة من التعارض عند استدعائها من أكثر من Thread بنفس الوقت
        # (سبب أخطاء AssertionError: self.__uid is not None المتكررة)
        # RLock (وليس Lock عادي) عشان نقدر نحمي تعديل قوائم الـ UI + التحديث معاً كوحدة واحدة
        # من نفس الـ Thread دون ما يصير Deadlock عند التداخل بين الدوال
        self._ui_lock = threading.RLock()
        
        self.SUPABASE_URL = "https://fbtrkfrzndfqfffixfzi.supabase.co"
        self.SUPABASE_KEY = "sb_publishable_9fzWVetwvxbXptXwZihR5g__RHnELA6"
        self.db = SupabaseManager(self.SUPABASE_URL, self.SUPABASE_KEY)

        self.current_lecture_filter = "upcoming"
        self.search_query = ""

        # Pagination Attributes
        self.current_page_num = 1
        self.page_size = 20

        # Session attributes
        self.current_user_id = None
        self.current_user_name = None
        self.current_user_img = None
        self.current_user_birth = None

        # -- عنصر القائمة الجانبية (نُنشئه مرة واحدة فقط لتفادي مشاكل الـ uid عند إعادة البناء) --
        self.drawer = ft.NavigationDrawer(
            controls=[],
            bgcolor=ft.colors.WHITE,
            elevation=0,
            shadow_color=ft.colors.TRANSPARENT,
            surface_tint_color=ft.colors.TRANSPARENT,
            indicator_color=ft.colors.TRANSPARENT
        )

        # مجلد تخزين الكاش محلياً
        self.cache_dir = "cache"
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)

        # بيانات افتراضية أولية
        self.default_members = [
            {"id": 1, "member": "إسماعيل شريف", "pwd": "123", "img": "default.png", "birth_date": "1995-01-01", "is_admin": True}
        ]

        self.default_lectures = [
            {
                "id": 1,
                "title": "مستقبل الذكاء الاصطناعي في البحث العلمي",
                "member_id": 0,
                "member_name": "د. أحمد علي",
                "member_img": "",
                "date": "2026-08-25",
                "completed_at": "2026-08-25",
                "type": "فلسفة",
                "finished": "true",
                "votes": 7,
                "suggested_by": "عقيل",
                "locked": "false",
                "summary": "file.pdf"
            }
        ]
        
        self.default_topics = [
            {"id": 1, "title": "قواعد كتابة الأوراق البحثية المحكمة", "suggested_by": "سارة", "category": "منهجية بحث", "votes": 9, "accepted": "false", "comments_count": 0}
        ]
        
        # UI Controls
        self.lectures_list = ft.ListView(expand=True, spacing=12, padding=5)
        self.topics_list = ft.ListView(expand=True, spacing=12, padding=5)
        self.speakers_list = ft.ListView(expand=True, spacing=1, padding=5)
        self.pagination_row = ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=10)

        self.search_field = ft.TextField(
            label="بحث في العناوين أو المحاضرين...",
            label_style=ft.TextStyle(color=ft.colors.BLUE_300, size=13),
            prefix=ft.Icon(ft.icons.SEARCH, color=ft.colors.BLUE_400, size=20),
            border_radius=10,
            border_color=ft.colors.BLUE_400,
            text_size=13,
            color=ft.colors.BLUE_400,
            height=45,
            content_padding=10,
            on_change=self.on_search_change
        )

        # -- بطاقة المحاضرة القادمة المرتقبة --
        self.upcoming_banner_content = ft.Column(spacing=0)
        self.upcoming_banner = ft.Container(
            content=self.upcoming_banner_content,
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_right,
                end=ft.alignment.bottom_left,
                colors=[ft.colors.INDIGO_900, ft.colors.BLUE_800]
            ),
            padding=16,
            border_radius=16,
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=10,
                color=ft.colors.BLACK12,
                offset=ft.Offset(0, 4)
            )
        )

        self.btn_finished = ft.ElevatedButton(
            "المكتملة",
            icon=ft.icons.CHECK_CIRCLE_OUTLINE,
            icon_color=ft.colors.BLUE_700,
            bgcolor=ft.colors.GREY_100,
            width=150,
            height=35,
            color=ft.colors.BLUE_700,
            on_click=lambda e: self.change_lecture_filter("finished")
        )
        self.btn_upcoming = ft.ElevatedButton(
            "القادمة",
            icon=ft.icons.SCHEDULE,
            icon_color="white",
            bgcolor=ft.colors.BLUE_700,
            width=150,
            height=35,
            color="white",
            on_click=lambda e: self.change_lecture_filter("upcoming")
        )

        self.setup_page()
        self.load_session()
        self.build_ui()

    def is_current_user_admin(self) -> bool:
        """فحص صلاحية المدير للمستخدم الحالي عبر حقل is_admin"""
        if not self.current_user_id:
            return False
        members_data = self.fetch_with_cache("members", self.default_members)
        current_member = next((m for m in members_data if str(m.get("id")) == str(self.current_user_id)), None)
        return bool(current_member.get("is_admin", False)) if current_member else False

    def setup_page(self):
        self.page.title = "ملتقى الفكر والدراسات العلمية"
        self.page.rtl = True
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.padding = 10
        self.page.bgcolor = ft.colors.GREY_100

    def load_session(self):
        session_file = os.path.join(self.cache_dir, "session.json")
        if os.path.exists(session_file):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.current_user_id = data.get("user_id")
                    self.current_user_name = data.get("user_name")
                    self.current_user_img = data.get("user_img")
                    self.current_user_birth = data.get("user_birth")
            except Exception:
                pass

    def save_session(self, user_id, user_name, img, birth):
        self.current_user_id = user_id
        self.current_user_name = user_name
        self.current_user_img = img
        self.current_user_birth = birth
        session_file = os.path.join(self.cache_dir, "session.json")
        try:
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump({"user_id": user_id, "user_name": user_name, "user_img": img, "user_birth": birth}, f, ensure_ascii=False)
        except Exception:
            pass

    def clear_session(self):
        self.current_user_id = None
        self.current_user_name = None
        self.current_user_img = None
        self.current_user_birth = None
        session_file = os.path.join(self.cache_dir, "session.json")
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
            except Exception:
                pass
        
        self.page.floating_action_button = ft.FloatingActionButton(visible=False)
        self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم تسجيل الخروج بنجاح", text_align="center"), bgcolor=ft.colors.BLUE_700))
        self.page.controls.clear()
        self.build_ui()
        self.safe_update()

    def safe_update(self):
        """
        تحديث آمن للصفحة يمنع تعارض التحديثات المتزامنة القادمة من أكثر من Thread
        (مثل الخيط الخلفي لمزامنة البيانات مع Supabase) مع الخيط الرئيسي للواجهة،
        وهو السبب الجذري لأخطاء AssertionError المتكررة.
        """
        with self._ui_lock:
            try:
                self.page.update()
            except Exception as ex:
                import traceback
                print(f"[safe_update] خطأ أثناء تحديث الصفحة: {ex}")
                traceback.print_exc()

    def safe_ctrl_update(self, ctrl):
        """نفس فكرة safe_update لكن لعنصر تحكم محدد بدل الصفحة كاملة."""
        with self._ui_lock:
            try:
                if getattr(ctrl, "page", None):
                    ctrl.update()
            except Exception as ex:
                print(f"[safe_ctrl_update] خطأ أثناء تحديث العنصر: {ex}")

    def get_cached_data_from_file(self, filename: str, default_value):
        file_path = os.path.join(self.cache_dir, f"{filename}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return default_value

    def set_cached_data_to_file(self, filename: str, data):
        file_path = os.path.join(self.cache_dir, f"{filename}.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def _lecture_to_db_payload(self, data: dict) -> dict:
        """يحوّل مفاتيح بيانات المحاضرة لتطابق اسم العمود الحقيقي (speaker) في جدول lectures بقاعدة البيانات."""
        payload = dict(data)
        if "member_name" in payload:
            payload["speaker"] = payload.pop("member_name")
        return payload

    def _lecture_from_db_payload(self, records: list) -> list:
        """يحوّل البيانات القادمة من قاعدة البيانات (عمود speaker) إلى member_name المستخدم داخلياً بالتطبيق."""
        for r in records:
            if "speaker" in r:
                r["member_name"] = r.pop("speaker")
        return records

    def fetch_with_cache(self, table_name: str, default_data, on_bg_updated=None):
        """
        استراتيجية Cache-First:
        ترجع البيانات المحلية فوراً لتظهر في الواجهة لحظياً،
        ثم تبدأ مَهمة في الخلفية لجلب البيانات الحديثة وتحديث الكاش.
        """
        cached_data = self.get_cached_data_from_file(table_name, None)
        
        def sync_in_background():
            try:
                remote_data = self.db.fetch_data(table_name)
                if remote_data is not None and len(remote_data) > 0:
                    if table_name == "lectures":
                        remote_data = self._lecture_from_db_payload(remote_data)
                    self.set_cached_data_to_file(table_name, remote_data)
                    if on_bg_updated:
                        # نحمي بناء عناصر الواجهة (clear + append) والتحديث معاً بنفس القفل
                        # لمنع تعارضها مع أي نقرة زر تستدعي safe_update() في نفس اللحظة
                        # (هذا هو السبب الحقيقي وراء AssertionError: self.__uid is not None)
                        with self._ui_lock:
                            on_bg_updated(remote_data)
            except Exception:
                pass

        threading.Thread(target=sync_in_background, daemon=True).start()

        if cached_data is not None:
            return cached_data
        return default_data

    def get_cached_member_image(self, img_column_value):
        remote_url = self.db.get_member_image(img_column_value)
        if not img_column_value:
            return remote_url

        avatars_cache_dir = os.path.join("assets", "avatars")
        if not os.path.exists(avatars_cache_dir):
            os.makedirs(avatars_cache_dir, exist_ok=True)

        local_image_path = os.path.join(avatars_cache_dir, img_column_value)
        
        if os.path.exists(local_image_path):
            return local_image_path

        def download_image():
            if self.db.is_connected:
                try:
                    response = requests.get(remote_url, timeout=5)
                    if response.status_code == 200:
                        with open(local_image_path, "wb") as f:
                            f.write(response.content)
                except Exception:
                    pass

        threading.Thread(target=download_image, daemon=True).start()
        return remote_url

    def open_login_dialog(self, e):
        pwd_field = ft.TextField(hint_text="أدخل كلمة السر", password=True, can_reveal_password=True, text_align=ft.TextAlign.RIGHT, text_size=15, border_radius=8, height=45, content_padding=10, color=BLUE, border_color=BLUE)
        error_text = ft.Text("", color=ft.colors.RED_700, text_align="center", size=13)

        def verify_login(e):
            entered_pwd = pwd_field.value.strip()
            if not entered_pwd:
                error_text.value = "الرجاء إدخال كلمة السر."
                self.safe_update()
                return

            members_data = self.fetch_with_cache("members", self.default_members)
            matched_member = next((m for m in members_data if str(m.get("pwd")).strip() == entered_pwd), None)

            if matched_member:
                uid = matched_member.get("id")
                uname = matched_member.get("member")
                self.save_session(uid, uname, matched_member.get("img"), matched_member.get("birth_date"))
                self.page.dialog.open = False
                self.safe_update()
                self.page.show_snack_bar(ft.SnackBar(content=ft.Text(f"مرحباً بك {uname}", text_align="center"), bgcolor=ft.colors.BLUE_700))
                self.page.controls.clear()
                self.build_ui()
                self.safe_update()
            else:
                error_text.value = "كلمة السر غير صحيحة"
                self.safe_update()

        dialog = ft.AlertDialog(
            title=ft.Text("سجل دخولك للمتابعة", text_align="center", size=15, color=ft.colors.INDIGO_700),
            content=ft.Column([ft.Container(height=10), pwd_field, ft.Row([error_text], alignment=ft.MainAxisAlignment.CENTER)], tight=True, spacing=5),
            actions=[
                ft.ElevatedButton("إلغاء", height=35, on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update()),
                ft.ElevatedButton("دخول", bgcolor=PRIMARY, color="white", height=35, on_click=verify_login)
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER
        )
        self.page.dialog = dialog
        dialog.open = True
        self.safe_update()

    def open_edit_profile_dialog(self, e):
        members_data = self.fetch_with_cache("members", self.default_members)
        current_member_data = next((m for m in members_data if m.get("id") == self.current_user_id), {})

        name_field = ft.TextField(label="الاسم", value=current_member_data.get("member", self.current_user_name or ""), text_align=ft.TextAlign.RIGHT, border_radius=8, border_color=BLUE, color=BLUE, height=45, content_padding=10)
        pwd_field = ft.TextField(label="كلمة السر الجديدة", value=current_member_data.get("pwd", ""), password=True, can_reveal_password=True, text_align=ft.TextAlign.RIGHT, border_radius=8, border_color=BLUE, color=BLUE, height=45, content_padding=10)
        birth_val = current_member_data.get("birth_date", "")
        birth_field = ft.TextField(label="تاريخ الميلاد", value=birth_val, read_only=True, text_align=ft.TextAlign.RIGHT, border_radius=8, border_color=BLUE, color=BLUE, expand=True, height=45, content_padding=10)

        def on_date_change(e):
            if date_picker.value:
                birth_field.value = date_picker.value.strftime("%Y-%m-%d")
                self.safe_update()

        date_picker = ft.DatePicker(on_change=on_date_change, first_date=datetime(1990, 1, 1), last_date=datetime.now())
        self.page.overlay.append(date_picker)
        date_btn = ft.IconButton(icon=ft.icons.CALENDAR_MONTH, icon_color=ft.colors.INDIGO_700, on_click=lambda _: date_picker.pick_date())
        birth_row = ft.Row([date_btn, birth_field], spacing=5)
        error_text = ft.Text("", color=ft.colors.RED_700, size=12)

        def save_changes(e):
            new_name = name_field.value.strip()
            new_pwd = pwd_field.value.strip()
            new_birth = birth_field.value.strip()

            if not new_name or not new_pwd:
                error_text.value = "الاسم وكلمة السر حقول إجبارية."
                self.safe_update()
                return

            updated_fields = {"member": new_name, "pwd": new_pwd, "birth_date": new_birth}
            if self.db.is_connected and self.current_user_id:
                try:
                    self.db.update_data("members", self.current_user_id, updated_fields)
                except Exception:
                    pass

            for m in members_data:
                if m.get("id") == self.current_user_id:
                    m.update(updated_fields)
            self.set_cached_data_to_file("members", members_data)
            self.save_session(self.current_user_id, new_name, self.current_user_img, self.current_user_birth)

            self.page.dialog.open = False
            self.safe_update()
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم تحديث بياناتك بنجاح", text_align="center"), bgcolor=DONE))
            self.page.controls.clear()
            self.build_ui()
            self.safe_update()

        dialog = ft.AlertDialog(
            title=ft.Text("تعديل البيانات الشخصية", text_align="center", size=15, color=PRIMARY),
            content=ft.Column([ft.Container(height=5), name_field, ft.Container(height=5), pwd_field, ft.Container(height=5), birth_row, error_text], tight=True, spacing=2),
            actions=[
                ft.ElevatedButton("إلغاء", height=35, on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update()),
                ft.ElevatedButton("حفظ", bgcolor=PRIMARY, color="white", height=35, on_click=save_changes)
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER
        )
        self.page.dialog = dialog
        dialog.open = True
        self.safe_update()

    def open_add_topic_dialog(self, e):
        if not self.current_user_name:
            self.open_login_dialog(e)
            return
        category_field = ft.Dropdown(
            hint_text="التصنيف",
            options=[ft.dropdown.Option("فلسفة"), ft.dropdown.Option("طب"), ft.dropdown.Option("ثقافي"), ft.dropdown.Option("معتقدات"), ft.dropdown.Option("علوم"), ft.dropdown.Option("تاريخ"), ft.dropdown.Option("رياضي"), ft.dropdown.Option("علم النفس"), ft.dropdown.Option("أساطير"), ft.dropdown.Option("لغات"), ft.dropdown.Option("أدبي"), ft.dropdown.Option("ديني"), ft.dropdown.Option("تقني"), ft.dropdown.Option("أخرى")], border_radius=8,
            border_color=BLUE,
        )
        title_field = ft.TextField(hint_text="عنوان المقترح أو المحاضرة", border_radius=8, height=45, text_align=ft.TextAlign.RIGHT, border_color=BLUE, color=BLUE)

        def save_new_topic(e):
            t_title = title_field.value.strip()
            t_cat = category_field.value.strip() if category_field.value else "عام"
            if not t_title:
                self.page.show_snack_bar(ft.SnackBar(content=ft.Text("الرجاء إدخال عنوان المقترح.", text_align="center"), bgcolor=ft.colors.GREY_800))
                return

            topics_data = self.fetch_with_cache("topics", self.default_topics)
            new_id = max([t.get("id", 0) for t in topics_data], default=0) + 1
            current_date = datetime.now().strftime("%d-%m-%Y")
            new_item = {
                "id": new_id,
                "title": t_title,
                "suggested_by": self.current_user_name,
                "category": t_cat,
                "votes": 0,
                "accepted": "false",
                "comments_count": 0,
                "created_at": current_date
            }

            if self.db.is_connected:
                try:
                    self.db.insert_data("topics", new_item)
                except Exception:
                    pass

            topics_data.insert(0, new_item)
            self.set_cached_data_to_file("topics", topics_data)

            self.page.dialog.open = False
            self.safe_update()
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم إضافة مقترحك بنجاح!", text_align="center"), bgcolor=ft.colors.TEAL_400))
            self.load_topics()

        dialog = ft.AlertDialog(
            title=ft.Text("إقترح عنوان أو أخبرنا ما يدور في ذهنك", text_align="center", size=15, color=PRIMARY),
            content=ft.Column([ft.Container(height=5), title_field, ft.Container(height=5), category_field], tight=True, spacing=10),
            actions=[
                ft.ElevatedButton("إلغاء", height=35, on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update()),
                ft.ElevatedButton("إضافة", bgcolor=PRIMARY, color="white", height=35, on_click=save_new_topic)
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER
        )
        self.page.dialog = dialog
        dialog.open = True
        self.safe_update()

    def open_add_member_dialog(self, e):
        if not self.is_current_user_admin():
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("عفواً، هذه الصلاحية للمدراء فقط", text_align="center"), bgcolor=ft.colors.RED_700))
            return

        name_field = ft.TextField(
            label="اسم العضو", 
            text_align=ft.TextAlign.RIGHT, 
            border_radius=8, 
            border_color=BLUE, 
            color=BLUE, 
            height=45, 
            content_padding=10
        )
        pwd_field = ft.TextField(
            label="كلمة السر", 
            password=True, 
            can_reveal_password=True, 
            text_align=ft.TextAlign.RIGHT, 
            border_radius=8, 
            border_color=BLUE, 
            color=BLUE, 
            height=45, 
            content_padding=10
        )
        error_text = ft.Text("", color=ft.colors.RED_700, size=12)

        def save_new_member(e):
            new_name = name_field.value.strip()
            new_pwd = pwd_field.value.strip()

            if not new_name or not new_pwd:
                error_text.value = "الاسم وكلمة السر حقول إجبارية."
                self.safe_update()
                return

            members_data = self.fetch_with_cache("members", self.default_members)
            new_id = max([m.get("id", 0) for m in members_data], default=0) + 1
            
            new_member = {
                "id": new_id,
                "member": new_name,
                "pwd": new_pwd,
                "img": "default.png",
                "is_admin": False
            }

            if self.db.is_connected:
                try:
                    self.db.insert_data("members", new_member)
                except Exception:
                    pass

            members_data.insert(0, new_member)
            self.set_cached_data_to_file("members", members_data)

            self.page.dialog.open = False
            self.safe_update()
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم تسجيل العضو الجديد بنجاح", text_align="center"), bgcolor=DONE))
            self.load_speakers()

        dialog = ft.AlertDialog(
            title=ft.Text("تسجيل عضو جديد", text_align="center", size=15, color=PRIMARY),
            content=ft.Column([
                ft.Container(height=5), 
                name_field, 
                ft.Container(height=5), 
                pwd_field, 
                error_text
            ], tight=True, spacing=5),
            actions=[
                ft.ElevatedButton("إلغاء", height=35, on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update()),
                ft.ElevatedButton("حفظ", bgcolor=PRIMARY, color="white", height=35, on_click=save_new_member)
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER
        )
        self.page.dialog = dialog
        dialog.open = True
        self.safe_update()

    def handle_tab_changing(self, e):
        is_admin = self.is_current_user_admin()
        if e.control.selected_index == 2 and is_admin:
            self.page.floating_action_button = ft.FloatingActionButton(
                content=ft.Icon(ft.icons.ADD, color="white", size=20),
                bgcolor=ft.colors.BLUE_500,
                on_click=self.open_add_member_dialog, 
                width=40, 
                height=40,
                visible=True
            )
        else:
            self.page.floating_action_button = ft.FloatingActionButton(visible=False)
        self.safe_update()

    def handle_delete_lecture(self, item):
        if not self.is_current_user_admin():
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("عفواً، هذه الصلاحية للمدراء فقط", text_align="center"), bgcolor=ft.colors.RED_700))
            return

        lec_id = item.get("id")
        lectures = self.fetch_with_cache("lectures", [])
        lectures = [l for l in lectures if l.get("id") != lec_id]
        self.set_cached_data_to_file("lectures", lectures)
        if self.db.is_connected:
            try:
                self.db.delete_data("lectures", lec_id)
            except Exception:
                pass
        self.load_all_data()
        self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم حذف المحاضرة بنجاح", text_align="center"), bgcolor=DONE))

    def handle_edit_lecture(self, item):
        if not self.is_current_user_admin():
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("عفواً، هذه الصلاحية للمدراء فقط", text_align="center"), bgcolor=ft.colors.RED_700))
            return

        title_field = ft.TextField(
            label="عنوان المحاضرة",
            value=item.get("title", ""), 
            text_align=ft.TextAlign.RIGHT, 
            border_radius=8,
            border_color=BLUE,
        )
        type_field = ft.Dropdown(
            hint_text="التصنيف",
            options=[
                ft.dropdown.Option("فلسفة"), ft.dropdown.Option("طب"), ft.dropdown.Option("ثقافي"), 
                ft.dropdown.Option("معتقدات"), ft.dropdown.Option("علوم"), ft.dropdown.Option("تاريخ"), 
                ft.dropdown.Option("رياضي"), ft.dropdown.Option("علم النفس"), ft.dropdown.Option("أساطير"), 
                ft.dropdown.Option("لغات"), ft.dropdown.Option("أدبي"), ft.dropdown.Option("ديني"), 
                ft.dropdown.Option("تقني"), ft.dropdown.Option("أخرى")
            ], 
            border_radius=8,
            border_color=BLUE,
            value=item.get("type")
        )
        
        is_currently_finished = str(item.get("finished", "false")).lower() in ["true", "1"]
        
        finish_checkbox = ft.Checkbox(
            value=is_currently_finished,
            label_position=ft.LabelPosition.RIGHT,
            #fill_color=ft.colors.TEAL_400,
        )
        finish_checkbox_rtl = ft.Row([
        ft.Text("إعتبارها كمكتملة", size=14, color=ft.colors.GREY_800),
        finish_checkbox
        ], spacing=0, alignment=ft.MainAxisAlignment.END, width=float("inf"))
        def save_edited_lecture(e):
            new_title = title_field.value.strip()
            if not new_title:
                return
            
            new_finished_status = "true" if finish_checkbox.value else "false"
            today_date_str = datetime.now().strftime("%Y-%m-%d")
            
            if new_finished_status == "true":
                completed_at_val = item.get("completed_at") or today_date_str
            else:
                completed_at_val = ""

            updated_fields = {
                "title": new_title,
                "type": type_field.value,
                "finished": new_finished_status,
                "completed_at": completed_at_val
            }

            item.update(updated_fields)

            if self.db.is_connected:
                try:
                    self.db.update_data("lectures", item.get("id"), updated_fields)
                except Exception:
                    pass

            # نقرأ الكاش مباشرة من الملف (بدون تشغيل مزامنة خلفية جديدة) لتفادي تعارضها
            # مع الحفظ اليدوي هنا - نفس سبب مشكلة عدم تحديث قائمة "المكتملة" بشكل صحيح:
            # fetch_with_cache كانت تشغّل جلب بيانات من الخادم في الخلفية، وأحياناً
            # يصل رد الخادم متأخراً ويكتب فوق حالة "مكتملة" التي حفظناها للتو بالبيانات القديمة
            lectures = self.get_cached_data_from_file("lectures", [])
            for l in lectures:
                if l.get("id") == item.get("id"):
                    l.update(updated_fields)
            self.set_cached_data_to_file("lectures", lectures)

            self.page.dialog.open = False
            self.safe_update()
            self.load_all_data()
            self.page.show_snack_bar(
                ft.SnackBar(content=ft.Text("تم تعديل المحاضرة وحالتها بنجاح", text_align="center"), bgcolor=DONE)
            )

        dialog = ft.AlertDialog(
            title=ft.Text("تعديل المحاضرة", size=15, text_align="center"),
            content=ft.Column(
                [
                    title_field, 
                    type_field, 
                    ft.Container(
                        content=finish_checkbox_rtl,
                        padding=ft.padding.only(top=5),
                    )
                ], 
                tight=True, 
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.START
            ),
            actions=[
                ft.ElevatedButton("إلغاء", on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update()),
                ft.ElevatedButton("حفظ", bgcolor=PRIMARY, color="white", on_click=save_edited_lecture)
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER
        )
        self.page.dialog = dialog
        dialog.open = True
        self.safe_update()

    def handle_assign_lecturer(self, item):
        if not self.is_current_user_admin():
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("عفواً، هذه الصلاحية للمدراء فقط", text_align="center"), bgcolor=ft.colors.RED_700))
            return

        members = self.fetch_with_cache("members", self.default_members)
        member_dropdown = ft.Dropdown(
            label="اختر المحاضر",
            options=[ft.dropdown.Option(m.get("member")) for m in members],
            border_radius=8
        )

        def save_assignment(e):
            selected_name = member_dropdown.value
            if not selected_name:
                return
            matched_m = next((m for m in members if m.get("member") == selected_name), {})
            member_id = matched_m.get("id", 0)

            update_ok = True
            if self.db.is_connected:
                update_ok = self.db.update_data(
                    "lectures", item.get("id"),
                    self._lecture_to_db_payload({"member_name": selected_name, "member_id": member_id})
                )

            if not update_ok:
                self.page.dialog.open = False
                self.safe_update()
                self.page.show_snack_bar(
                    ft.SnackBar(content=ft.Text("تعذر حفظ التعيين على الخادم، يرجى المحاولة لاحقاً", text_align="center"), bgcolor=ft.colors.RED_700)
                )
                return

            item["member_name"] = selected_name
            item["member_id"] = member_id

            # نقرأ الكاش مباشرة من الملف (بدون تشغيل مزامنة خلفية جديدة) لتفادي تعارضها مع الحفظ اليدوي هنا
            lectures = self.get_cached_data_from_file("lectures", [])
            for l in lectures:
                if l.get("id") == item.get("id"):
                    l["member_name"] = selected_name
                    l["member_id"] = member_id
            self.set_cached_data_to_file("lectures", lectures)
            self.page.dialog.open = False
            self.safe_update()
            self.load_all_data()
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم تعيين المحاضر بنجاح", text_align="center"), bgcolor=DONE))

        dialog = ft.AlertDialog(
            title=ft.Text("تعيين محاضر للمحاضرة", size=15, text_align="center"),
            content=member_dropdown,
            actions=[
                ft.ElevatedButton("إلغاء", on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update()),
                ft.ElevatedButton("تعيين", bgcolor=PRIMARY, color="white", on_click=save_assignment)
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER
        )
        self.page.dialog = dialog
        dialog.open = True
        self.safe_update()

    def handle_delete_topic(self, item):
        if not self.is_current_user_admin():
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("عفواً، هذه الصلاحية للمدراء فقط", text_align="center"), bgcolor=ft.colors.RED_700))
            return

        top_id = item.get("id")
        topics = self.fetch_with_cache("topics", [])
        topics = [t for t in topics if t.get("id") != top_id]
        self.set_cached_data_to_file("topics", topics)
        if self.db.is_connected:
            try:
                self.db.delete_data("topics", top_id)
            except Exception:
                pass
        self.load_all_data()
        self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم حذف المقترح بنجاح", text_align="center"), bgcolor=DONE))

    def handle_edit_topic(self, item):
        if not self.is_current_user_admin():
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("عفواً، هذه الصلاحية للمدراء فقط", text_align="center"), bgcolor=ft.colors.RED_700))
            return

        title_field = ft.TextField(
            label="عنوان المقترح", 
            value=item.get("title", ""), 
            text_align=ft.TextAlign.RIGHT, 
            border_radius=8
        )
        category_field = ft.Dropdown(
            hint_text="التصنيف",
            options=[
                ft.dropdown.Option("فلسفة"), ft.dropdown.Option("طب"), ft.dropdown.Option("ثقافي"), 
                ft.dropdown.Option("معتقدات"), ft.dropdown.Option("علوم"), ft.dropdown.Option("تاريخ"), 
                ft.dropdown.Option("رياضي"), ft.dropdown.Option("علم النفس"), ft.dropdown.Option("أساطير"),
                ft.dropdown.Option("لغات"), ft.dropdown.Option("إجتماعي"),
                ft.dropdown.Option("لغات"), ft.dropdown.Option("أدبي"), ft.dropdown.Option("ديني"), 
                ft.dropdown.Option("تقني"), ft.dropdown.Option("أخرى")
            ], 
            border_radius=8,
            border_color=BLUE,
            value=item.get("category", "عام")
        )

        def save_edited_topic(e):
            new_title = title_field.value.strip()
            if not new_title:
                return

            updated_fields = {
                "title": new_title,
                "category": category_field.value
            }

            item.update(updated_fields)

            if self.db.is_connected:
                try:
                    self.db.update_data("topics", item.get("id"), updated_fields)
                except Exception:
                    pass

            topics = self.fetch_with_cache("topics", [])
            for t in topics:
                if t.get("id") == item.get("id"):
                    t.update(updated_fields)
            self.set_cached_data_to_file("topics", topics)

            self.page.dialog.open = False
            self.safe_update()
            self.load_all_data()
            self.page.show_snack_bar(
                ft.SnackBar(content=ft.Text("تم تعديل المقترح بنجاح", text_align="center"), bgcolor=DONE)
            )

        dialog = ft.AlertDialog(
            title=ft.Text("تعديل المقترح", size=15, text_align="center"),
            content=ft.Column([title_field, category_field], tight=True, spacing=12),
            actions=[
                ft.ElevatedButton("إلغاء", on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update()),
                ft.ElevatedButton("حفظ", bgcolor=PRIMARY, color="white", on_click=save_edited_topic)
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER
        )
        self.page.dialog = dialog
        dialog.open = True
        self.safe_update()

    def handle_accept_topic(self, item):
        if not self.is_current_user_admin():
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("عفواً، هذه الصلاحية للمدراء فقط", text_align="center"), bgcolor=ft.colors.RED_700))
            return

        item["accepted"] = "true"
        lectures_data = self.fetch_with_cache("lectures", self.default_lectures)
        new_lec = {
            "id": max([l.get("id", 0) for l in lectures_data], default=0) + 1,
            "title": item.get("title"),
            "member_id": 0,
            "member_name": "لم يحدد",
            "member_img": "",
            "date": self.get_next_friday_date(),
            "completed_at": "",
            "type": item.get("category", "عام"),
            "finished": "false",
            "votes": 0,
            "suggested_by": item.get("suggested_by"),
            "locked": "false",
            "summary": ""
        }
        lectures_data.insert(0, new_lec)
        
        topics_data = self.fetch_with_cache("topics", self.default_topics)
        for t in topics_data:
            if t.get("id") == item.get("id"):
                t["accepted"] = "true"

        self.set_cached_data_to_file("lectures", lectures_data)
        self.set_cached_data_to_file("topics", topics_data)
        
        if self.db.is_connected:
            try:
                self.db.insert_data("lectures", self._lecture_to_db_payload(new_lec))
                self.db.update_data("topics", item.get("id"), {"accepted": "true"})
            except Exception:
                pass

        self.load_all_data()
        self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم نقل المقترح إلى المحاضرات القادمة بنجاح", text_align="center"), bgcolor=DONE))

    def open_admin_panel(self, e):
        if not self.is_current_user_admin():
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("عفواً، الوصول للوحة التحكم للمدراء فقط", text_align="center"), bgcolor=ft.colors.RED_700))
            return

        admin_topics_list = ft.ListView(expand=True, spacing=10, height=300)

        def toggle_admin(m_item):
        	current_status = bool(m_item.get("is_admin", False))
        	new_status = not current_status
        	m_item["is_admin"] = new_status
        	if self.db.is_connected:
        		try:
        			self.db.update_data("members", m_item.get("id"), {"is_admin": new_status})
        		except Exception:
        			pass
        	all_members = self.get_cached_data_from_file("members", [])
        	for mem in all_members:
        		if mem.get("id") == m_item.get("id"):
        			mem["is_admin"] = new_status
        	self.set_cached_data_to_file("members", all_members)
        	status_msg = "تم تعيينه مديرا" if new_status else "تم إلغاء صفة المدير"
        	self.page.show_snack_bar(ft.SnackBar(content=ft.Text(status_msg, text_align="center"), bgcolor=DONE))
        	refresh_admin_list()

        def delete_member(m_item):
        	m_id = m_item.get("id")
        	members_data = self.get_cached_data_from_file("members", [])
        	members_data = [m for m in members_data if m.get("id") != m_id]
        	self.set_cached_data_to_file("members", members_data)
        	if self.db.is_connected:
        		try:
        			self.db.delete_data("members", m_id)
        		except Exception:
        			pass
        	self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم حذف العضو بنجاح", text_align="center"), bgcolor=DONE))
        	refresh_admin_list()
	
        def refresh_admin_list():
            # نعيد قراءة قائمة الأعضاء من الكاش في كل مرة بدل الاعتماد على نسخة قديمة
            # ثابتة (topics_data) كانت السبب في بقاء العضو المحذوف ظاهراً في القائمة
            # كل عملية بناء للقائمة + التحديث محمية بنفس القفل حتى لا تتعارض مع أي
            # Thread خلفي يحدّث الصفحة بنفس اللحظة (وهو سبب مشاكل الإغلاق/الأخطاء السابقة)
            with self._ui_lock:
                current_members = self.get_cached_data_from_file("members", self.default_members)
                admin_topics_list.controls.clear()
                for item in current_members:
                    t_id = item.get("id")
                    t_title = item.get("member", "")
                    is_acc = str(item.get("is_admin", "false")).lower() in ["true", "1"]
                    def accept_topic(it=item):
                        self.handle_accept_topic(it)
                        refresh_admin_list()

                    admin_btn = ft.IconButton(
                        ft.icons.ADMIN_PANEL_SETTINGS if is_acc else ft.icons.PERSON_OUTLINE,
                        icon_size=18,
                        icon_color=ft.colors.TEAL_400 if is_acc else ft.colors.BLUE_200,
                        on_click=lambda e, mi=item:toggle_admin(mi)
                    )
                    del_mem_btn = ft.IconButton(
                        ft.icons.DELETE,
                        icon_color=ft.colors.RED_200,
                        icon_size=14,
                        on_click=lambda e, mi=item: delete_member(mi)
                    )

                    admin_topics_list.controls.append(
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                ft.Image(src=f'avatars/{item.get("img")}', width=50,height=50, border_radius=25),
                                ft.Text(t_title, size=13,  color=BLUE, expand=True)]),
                                ft.Row([admin_btn, del_mem_btn], spacing=0),
                            ], spacing=0),
                            padding=8,
                            bgcolor=ft.colors.WHITE,
                            border_radius=8,
                            height=100,
                        )
                    )
                try:
                    self.safe_ctrl_update(dialog)
                except Exception:
                    pass

        dialog = ft.AlertDialog(
            title=ft.Text("لوحة إدارة الأعضاء", size=15, weight=ft.FontWeight.BOLD, color=PRIMARY, text_align="center"),
            content=ft.Container(
                width=400,
                content=ft.Column([
                    ft.Text("يمكنك حذف عضو أو تغيير صلاحيته", size=12, color=BLUE, text_align="right"),
                    admin_topics_list
                ], tight=True, spacing=10)
            ),
            actions=[
                ft.ElevatedButton("إغلاق", height=35, on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update())
            ],
            actions_alignment=ft.MainAxisAlignment.CENTER,
        )

        # نعرّف dialog أولاً ثم نملأ القائمة، حتى لا تُستدعى refresh_admin_list (وتحاول تحديث dialog)
        # قبل أن يكون هذا المتغير معرّفاً في نطاق الدالة
        refresh_admin_list()

        self.page.dialog = dialog
        dialog.open = True
        self.safe_update()

    def build_ui(self):
        auth_action_controls = []
        is_admin = self.is_current_user_admin()
        # -- عنصر ملاحة أنيق بدون حواف (Modern Borderless Nav Tile) --
        def close_drawer_then(handler):
            def _wrapped(e):
                # نغلق الـ drawer أولاً بتحديث مستقل خاص به، ثم نستدعي الـ handler بعدها.
                # فتح نافذة (Dialog) في نفس لحظة إغلاق الـ Drawer ضمن تحديث واحد كان يسبب
                # تعارضاً في طبقات العرض (Navigator) يمنع إغلاق النافذة لاحقاً - وهو سبب
                # مشكلة عدم إغلاق نافذتي "تعديل البيانات" و"لوحة إدارة الأعضاء".
                self.drawer.open = False
                self.safe_update()
                if handler:
                    handler(e)
            return _wrapped

        def nav_tile(icon, label, color=ft.colors.WHITE, subtitle=None, bgcolor=ft.colors.WHITE12, on_click=None):
            return ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Container(
                            content=ft.Icon(icon, color=color, size=19),
                            bgcolor=bgcolor,
                            padding=9,
                            border_radius=100,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(label, color=color, size=13, weight=ft.FontWeight.W_600),
                                ft.Text(subtitle, color=ft.colors.WHITE60, size=10) if subtitle else ft.Container(height=0),
                            ],
                            spacing=1,
                            expand=True,
                        ),
                    ],
                    spacing=12,
                ),
                padding=ft.padding.symmetric(horizontal=14, vertical=10),
                border_radius=14,
                ink=True,
                on_click=close_drawer_then(on_click),
            )

        drawer_items = []

        if self.current_user_id:
            drawer_items.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                content=ft.Image(src=f"avatars/{self.current_user_img}", width=75, height=75, border_radius=50, fit=ft.ImageFit.COVER),
                                border_radius=50,
                                padding=2,
                                border=ft.border.all(1,"white")
                            ),
                            ft.Text(f"{self.current_user_name}", color=ft.colors.WHITE, size=15, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"مواليد: {self.current_user_birth}", color=ft.colors.BLUE_300, size=11, overflow=ft.TextOverflow.ELLIPSIS) if self.current_user_birth else ft.Container(height=0, visible =False),
                            ft.Container(
                                content=ft.Text("مدير" if is_admin else "عضو", size=13, color=ft.colors.WHITE, text_align ="center"),
                                bgcolor=ft.colors.WHITE24,
                                padding=ft.padding.only (bottom=5),
                                border_radius=20,
                                width=60
                            ) if is_admin else ft.Container(visible=False),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    padding=ft.padding.only(top=30, bottom=22),
                    alignment=ft.alignment.center,
                    gradient=ft.LinearGradient(
                        begin=ft.alignment.top_center,
                        end=ft.alignment.bottom_center,
                        colors=[PRIMARY, BLUE],
                    ),
                )
            )
            drawer_items.append(ft.Container(height=10))
            if is_admin:
                drawer_items.append(
                    nav_tile(
                        ft.icons.ADMIN_PANEL_SETTINGS_ROUNDED,
                        "إدارة الأعضاء",
                        color=BLUE,
                        #subtitle="إدارة المقترحات والمحاضرات",
                        bgcolor=ft.colors.BLUE_50,
                        on_click=self.open_admin_panel,
                    )
                )
            drawer_items.extend([
            ft.Container(height=5),
                ft.Divider(height=1, color=ft.colors.GREY_200, thickness=1),
                nav_tile(
                    ft.icons.EDIT_NOTE_ROUNDED,
                    "تعديل بياناتي",
                    color=BLUE,
                    bgcolor=ft.colors.BLUE_50,
                    on_click=self.open_edit_profile_dialog,
                ),
                ft.Container(height=5),
                ft.Divider(height=1, color=ft.colors.GREY_200, thickness=1),
                ft.Container(height=5),
                nav_tile(
                    ft.icons.LOGOUT_ROUNDED,
                    "تسجيل خروج",
                    color=ft.colors.RED_300,
                    bgcolor=ft.colors.RED_50,
                    on_click=lambda e: self.clear_session(),
                ),
            ])
        else:
            drawer_items.extend([
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Container(
                                content=ft.Image(src="avatars/default.png", width=70, height=70, fit=ft.ImageFit.COVER, border_radius=50),
                                padding=2,
                                border_radius=50,
                                border=ft.border.all(1, "white")
                            ),
                            ft.Text("مرحباً بك", color=ft.colors.WHITE, size=15, weight=ft.FontWeight.BOLD),
                            ft.Text("سجّل الدخول للمتابعة", color=ft.colors.WHITE70, size=11),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    padding=ft.padding.only(top=30, bottom=22),
                    alignment=ft.alignment.center,
                    gradient=ft.LinearGradient(
                        begin=ft.alignment.top_center,
                        end=ft.alignment.bottom_center,
                        colors=[PRIMARY, BLUE],
                    ),
                ),
                ft.Container(height=10),
                nav_tile(
                    ft.icons.LOGIN_ROUNDED,
                    "تسجيل الدخول",
                    color=BLUE,
                    bgcolor=ft.colors.BLUE_50,
                    on_click=self.open_login_dialog,
                ),
            ])

        drawer_items.append(
            ft.Container(
                content=ft.TextButton("بلازما", style=ft.ButtonStyle(color="grey"), on_click=lambda _: self.page.launch_url("https://www.facebook.com/plasma.pc")),
                alignment=ft.alignment.center,
                height=400
            )
        )

        self.drawer.controls = drawer_items

        # -- رأس التطبيق الحديث (Modern Custom Header) --
        header = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            # جهة اليمين: الشعار والاسم مع شارة ترحيبية
                            ft.Row(
                                controls=[
                                    ft.Container(
                                        content=ft.Icon(ft.icons.AUTO_STORIES_ROUNDED, color=ft.colors.WHITE, size=24),
                                        bgcolor=ft.colors.WHITE12,
                                        padding=10,
                                        border_radius=12,
                                    ),
                                    ft.Column(
                                        controls=[
                                            ft.Text("ملتقى الفكر", size=18, weight=ft.FontWeight.BOLD, color=ft.colors.WHITE),
                                            ft.Text("منصة الدراسات والمقترحات والبحوث العلمية", size=11, color=ft.colors.BLUE_100),
                                        ],
                                        spacing=1,
                                    )
                                ],
                                spacing=12
                            ),
                            # جهة اليسار: كبسولة أزرار التحكم والبروفايل
                            #drawer button
                            ft.IconButton(
            icon=ft.icons.MENU, 
            icon_color =ft.colors.GREY_100,
            on_click=lambda e: self.page.show_drawer(self.drawer) # أمر فتح النافذة
        ),
                            #ft.Container(
#                                content=ft.Row(auth_action_controls, spacing=4, alignment=ft.MainAxisAlignment.CENTER),
#                                bgcolor=ft.colors.WHITE12,
#                                padding=ft.padding.symmetric(horizontal=8, vertical=4),
#                                border_radius=20,
#                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.START
            ),
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_right,
                end=ft.alignment.bottom_left,
                colors=[ft.colors.INDIGO_900, ft.colors.BLUE_800, ft.colors.INDIGO_600]
            ),
            padding=ft.padding.only(left=16, right=16, top=14, bottom=14),
            border_radius=ft.border_radius.all(16),
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=12,
                color=ft.colors.BLACK26,
                offset=ft.Offset(0, 4)
            )
        )
        
        lectures_tab = ft.Column(
            controls=[
                ft.Container(
                    padding=ft.padding.symmetric(vertical=5),
                    content=ft.Row([self.btn_upcoming, self.btn_finished], alignment=ft.MainAxisAlignment.CENTER, spacing=15)
                ),
                self.lectures_list,
                self.pagination_row
            ],
            expand=True
        )

        add_topic_btn = ft.ElevatedButton(
            "إقتراح",
            icon=ft.icons.ADD_COMMENT,
            bgcolor=ft.colors.BLUE_500,
            color=ft.colors.WHITE,
            height=36,
            on_click=self.open_add_topic_dialog
        )

        topics_tab = ft.Column(
            controls=[
                ft.Container(
                    padding=ft.padding.only(top=10, bottom=5, left=20, right=20),
                    content=ft.Row([
                        ft.Text("بنك العناوين والمقترحات", size=14, color=BLUE),
                        add_topic_btn
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                ),
                self.topics_list
            ],
            expand=True
        )
        total_members = self.fetch_with_cache("members", self.default_members)

        members_header = ft.Container(content=ft.Row([
            ft.Text(f"أعضاء الملتقى ( {len(total_members)} )", color=BLUE)
        ]), padding=ft.padding.only(top=20, right=10, left=10))

        speakers_tab = ft.Column([members_header, self.speakers_list], expand=True)

        tabs = ft.Tabs(
            selected_index=0,
            on_change=lambda e: self.handle_tab_changing(e),
            animation_duration=900,
            unselected_label_color=ft.colors.BLUE_600,
            tabs=[
                ft.Tab(text="المحاضرات", icon=ft.icons.EVENT_NOTE, content=lectures_tab),
                ft.Tab(text="مقترحات", icon=ft.icons.LIGHTBULB, content=topics_tab),
                ft.Tab(text="الأعضاء", icon=ft.icons.PERSON, content=speakers_tab),
            ],
            expand=True
        )

        self.page.add(header, self.upcoming_banner, self.search_field, tabs)
        self.load_all_data()

    def load_all_data(self):
        self.load_lectures()
        self.load_topics()
        self.load_speakers()
        self.update_upcoming_banner()

    def on_search_change(self, e):
        self.search_query = e.control.value.lower()
        self.current_page_num = 1
        self.load_lectures()
        self.load_topics()

    def handle_vote(self, item: dict, table_name: str):
        if not self.current_user_id:
            self.open_login_dialog(None)
            return

        is_admin = self.is_current_user_admin()
        if table_name == "lectures":
            is_locked = str(item.get("locked", "false")).lower() in ["true", "1"]
            if is_locked and not is_admin:
                self.page.show_snack_bar(ft.SnackBar(content=ft.Text("هذه المحاضرة مقفلة، لا يمكن التفاعل أو التصويت عليها", text_align="center"), bgcolor=ft.colors.RED_700))
                return

        record_id = item.get("id")
        votes_cache_file = "user_votes"
        user_votes_data = self.fetch_with_cache(votes_cache_file, [])

        already_voted = any(
            str(v.get("user_id")) == str(self.current_user_id) and
            str(v.get("record_id")) == str(record_id) and
            str(v.get("table_name")) == str(table_name)
            for v in user_votes_data
        )

        if already_voted:
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("قمت بالتصويت، لا يمكنك التصويت مرة أخرى!", text_align="center"), bgcolor=ft.colors.GREY_800))
            return

        item["votes"] = item.get("votes", 0) + 1
        if self.db.is_connected and record_id:
            try:
                self.db.update_data(table_name, record_id, {"votes": item["votes"]})
            except Exception:
                pass
        
        data = self.fetch_with_cache(table_name, [])
        for d in data:
            if d.get("id") == record_id:
                d["votes"] = item["votes"]
        self.set_cached_data_to_file(table_name, data)

        user_votes_data.append({
            "user_id": self.current_user_id,
            "record_id": record_id,
            "table_name": table_name
        })
        self.set_cached_data_to_file(votes_cache_file, user_votes_data)

        self.load_all_data()
        self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم تسجيل صوتك بنجاح", text_align="center"), bgcolor=DONE))

    def get_next_friday_date(self):
        today = datetime.now()
        days_ahead = 4 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_friday = today + timedelta(days=days_ahead)
        return next_friday.strftime("%Y-%m-%d")

    def update_upcoming_banner(self):
        data = self.fetch_with_cache("lectures", self.default_lectures)
        upcoming_list = [item for item in data if str(item.get("finished", "false")).lower() in ["false", "0"]]

        self.upcoming_banner_content.controls.clear()
        
        if not upcoming_list:
            self.upcoming_banner_content.controls.append(
                ft.Row(
                    controls=[
                        ft.Icon(ft.icons.INFO_OUTLINE_ROUNDED, color=ft.colors.WHITE70, size=20),
                        ft.Text("لا توجد محاضرات قادمة مجدولة حالياً", color=ft.colors.WHITE70, size=13)
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=8
                )
            )
        else:
            next_lec = upcoming_list[0]
            next_friday_str = self.get_next_friday_date()
            next_lec["date"] = next_friday_str
            member_name = next_lec.get("member_name", "غير محدد")
            category = next_lec.get("type", "عام")

            self.upcoming_banner_content.controls.append(
                ft.Column(
                    controls=[
                        # الشريط العلوي: شارة نوع المحاضرة + تاريخ الموعد
                        ft.Row(
                            controls=[
                                ft.Container(
                                    content=ft.Row([
                                        ft.Icon(ft.icons.BOOK, color=ft.colors.GREY_100, size=14),
                                        ft.Text("المحاضرة المرتقبة", color=ft.colors.WHITE, size=11, weight=ft.FontWeight.BOLD)
                                    ], spacing=4),
                                    bgcolor=ft.colors.WHITE12,
                                    padding=ft.padding.symmetric(horizontal=10, vertical=4),
                                    border_radius=20
                                ),
                                ft.Container(
                                    content=ft.Row([
                                        ft.Icon(ft.icons.EVENT_AVAILABLE_ROUNDED, color=ft.colors.CYAN_200, size=14),
                                        ft.Text(f"الجمعة: {next_friday_str}", color=ft.colors.CYAN_100, size=11, weight=ft.FontWeight.W_600)
                                    ], spacing=4),
                                    bgcolor=ft.colors.BLACK12,
                                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                    border_radius=8
                                )
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                        ),
                        # عنوان المحاضرة
                        ft.Text(
                            next_lec.get("title", ""),
                            color=ft.colors.BLUE_100,
                            size=14,
                            max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS
                        ),

                        # الشريط السفلي: التصنيف واسم المحاضر
                        ft.Row(
                            controls=[
                                ft.Row([
                                    ft.Container(
                                        content=ft.Icon(ft.icons.PERSON_ROUNDED, color=ft.colors.WHITE, size=14),
                                        bgcolor=ft.colors.BLUE_600,
                                        padding=4,
                                        border_radius=15
                                    ),
                                    ft.Text(member_name, color=ft.colors.BLUE_100, size=12, weight=ft.FontWeight.W_500)
                                ], spacing=6),

                                ft.Container(
                                    content=ft.Text(category, color=ft.colors.WHITE, size=10),
                                    bgcolor=ft.colors.WHITE24,
                                    padding=ft.padding.only(bottom=5, right=5, left=5),
                                    border_radius=6
                                )
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER
                        )
                    ]
                )
            )
        self.safe_ctrl_update(self.upcoming_banner)

    def change_lecture_filter(self, filter_type: str):
        self.current_lecture_filter = filter_type
        self.current_page_num = 1
        if filter_type == "finished":
            self.btn_finished.bgcolor = ft.colors.TEAL_300
            self.btn_finished.color = ft.colors.WHITE
            self.btn_finished.icon_color = "white"
            self.btn_upcoming.icon_color = ft.colors.BLUE_700
            self.btn_upcoming.bgcolor = ft.colors.GREY_100
            self.btn_upcoming.color = ft.colors.BLUE_700
        else:
            self.btn_upcoming.bgcolor = ft.colors.BLUE_700
            self.btn_upcoming.color = ft.colors.WHITE
            self.btn_upcoming.icon_color = "white"
            self.btn_finished.icon_color = ft.colors.BLUE_700
            self.btn_finished.bgcolor = ft.colors.GREY_100
            self.btn_finished.color = ft.colors.BLUE_700
        self.load_lectures()

    def load_speakers(self):
        def render_speakers_list(speakers_data):
            self.speakers_list.controls.clear()
            lectures = self.get_cached_data_from_file("lectures", self.default_lectures)
            current_is_admin = self.is_current_user_admin()

            for item in speakers_data:
                name = item.get("member", "")
                member_id = item.get("id", 1)
                img_column_value = item.get("img", "")
                contact_url = item.get("contact")
                is_admin = bool(item.get("is_admin", False))

                if self.search_query and self.search_query not in name.lower():
                    continue
                count = len([l for l in lectures if str(l.get("member_id")) == str(member_id)])
                img_src = self.get_cached_member_image(img_column_value)
                trailing_row = ft.Row([
                    ft.IconButton("facebook", icon_color=PRIMARY, on_click=lambda _: self.page.launch_url(contact_url)) if contact_url else ft.Container(visible=False)
                ], spacing=0, tight=True)

                card = ft.Card(
                    content=ft.Container(
                        padding=5,
                        content=ft.ListTile(
                            leading=ft.Container(
                                height=50, width=50,
                                content=ft.CircleAvatar(content=ft.Image(src=img_src, fit=ft.ImageFit.COVER, border_radius=50))
                            ),
                            title=ft.Row([
                                ft.Container(height=5, width=5,
                                    bgcolor=ft.colors.TEAL_300,
                                    border_radius=5,
                                    visible=is_admin
                                ),
                                ft.Text(name, size=14, color=BLUE)
                            ], spacing=2),
                            subtitle=ft.Text(f" قدم {count} محاضرة", color=ft.colors.GREY_500, size=12),
                            trailing=trailing_row
                        ), bgcolor="white",
                        border_radius=15
                    )
                )
                self.speakers_list.controls.append(card)

            if not self.speakers_list.controls:
                self.speakers_list.controls.append(
                    ft.Container(content=ft.Text("لا يوجد أعضاء", color=ft.colors.GREY_600), alignment=ft.alignment.center, padding=30)
                )
            self.safe_update()

        speakers = self.fetch_with_cache("members", self.default_members, on_bg_updated=render_speakers_list)
        render_speakers_list(speakers)

    def load_lectures(self):
        def render_lectures_list(data):
            self.lectures_list.controls.clear()
            self.pagination_row.controls.clear()

            filtered_items = []
            for item in data:
                finished_val = str(item.get("finished", "false")).lower()
                match_filter = (
                    (self.current_lecture_filter == "finished" and finished_val in ["true", "1"]) or
                    (self.current_lecture_filter == "upcoming" and finished_val in ["false", "0"])
                )
                if not match_filter:
                    continue

                title = item.get("title", "").lower()
                member_name = item.get("member_name", "").lower()
                if self.search_query and self.search_query not in title and self.search_query not in member_name:
                    continue
                filtered_items.append(item)

            total_items = len(filtered_items)
            total_pages = max((total_items + self.page_size - 1) // self.page_size, 1)
            if self.current_page_num > total_pages:
                self.current_page_num = total_pages

            start_idx = (self.current_page_num - 1) * self.page_size
            current_page_items = filtered_items[start_idx:start_idx + self.page_size]

            members_counter = self.get_cached_data_from_file("members", self.default_members)
            is_admin = self.is_current_user_admin()

            for item in current_page_items:            
                item["total"] = len(members_counter)
                finished_val = str(item.get("finished", "false")).lower()
                click_handler = None if finished_val in ["false", "0"] else self.open_lecture_detail_view
                
                self.lectures_list.controls.append(
                    LectureCard(
                        item, 
                        is_admin, 
                        on_vote_click=self.handle_vote, 
                        on_click=click_handler,
                        on_delete_click=self.handle_delete_lecture,
                        on_edit_click=self.handle_edit_lecture,
                        on_assign_lecturer=self.handle_assign_lecturer
                    )
                )
                    
            if not self.lectures_list.controls:
                self.lectures_list.controls.append(
                    ft.Container(content=ft.Text("لا توجد محاضرات", color=ft.colors.GREY_600), alignment=ft.alignment.center, padding=30)
                )
            else:
                prev_btn = ft.IconButton(icon=ft.icons.CHEVRON_LEFT, disabled=self.current_page_num <= 1, on_click=lambda e: self.change_page(-1))
                next_btn = ft.IconButton(icon=ft.icons.CHEVRON_RIGHT, disabled=self.current_page_num >= total_pages, on_click=lambda e: self.change_page(1))
                page_indicator = ft.Text(f"صفحة {self.current_page_num} من {total_pages}", size=12, color="grey")
                self.pagination_row.controls.extend([prev_btn, page_indicator, next_btn])

            self.safe_update()

        data = self.fetch_with_cache("lectures", self.default_lectures, on_bg_updated=render_lectures_list)
        render_lectures_list(data)

    def change_page(self, direction: int):
        self.current_page_num += direction
        self.load_lectures()

    def open_summary_view(self):
    	print("+++++++")
    	summary_view = ft.View(
    	"/ok",
    	controls=[ft.Text("Summary")]
    	)
    	self.page.views.append(summary_view)
    	self.page.go("/ok")
    	self.safe_update()
    def open_lecture_detail_view(self, lecture_item: dict):
        # علم للتحكم بحلقة التحديث التلقائي للتعليقات، يوقَف فور مغادرة الصفحة
        view_state = {"active": True}

        def go_back(e):
            view_state["active"] = False
            self.page.views.pop()
            self.safe_update()

        lec_id = lecture_item.get("id")
        is_locked = str(lecture_item.get("locked", "false")).lower() in ["true", "1"]
        has_attachment = bool(lecture_item.get("summary"))
        is_admin = self.is_current_user_admin()
        
        comment_input = ft.TextField(
            label="أضف تعليقك...",
            label_style=ft.TextStyle(color=BLUE, size=13),
            border_radius=8, 
            multiline=True, 
            min_lines=1,
            max_lines=3, 
            disabled=is_locked and not is_admin,
            color=BLUE,
            border_color=ft.colors.BLUE_200,
            content_padding=20
        )
        rating_dropdown = ft.Dropdown(
            label="كيف كانت المحاضرة؟",
            options=[ft.dropdown.Option("ممتاز"), ft.dropdown.Option("جيد جداً"), ft.dropdown.Option("جيد"), ft.dropdown.Option("لا بأس"), ft.dropdown.Option("لم تعجبني")],
            border_color=ft.colors.BLUE_200,
            color=BLUE,
            disabled=is_locked and not is_admin
        )

        comments_column = ft.Column(spacing=8)

        def load_comments():
            comments_data = self.fetch_with_cache("lecture_comments", [{"id": 1, "lecture_id": lec_id, "author": "عضو", "content": "محتوى قيم جداً.", "date": "2026-08-19", "rating": "ممتاز"}])
            filtered_comments = [c for c in comments_data if str(c.get("lecture_id")) == str(lec_id)]
            
            members_data = self.fetch_with_cache("members", self.default_members)

            comments_column.controls.clear()
            
            if not filtered_comments:
                comments_column.controls.append(
                    ft.Container(
                        content=ft.Text("لا توجد تعليقات", color=ft.colors.GREY_600, size=13),
                        alignment=ft.alignment.center,
                        padding=20
                    )
                )
            else:
                for c in filtered_comments:
                    is_owner = self.current_user_name and c.get("author") == self.current_user_name
                    
                    author_name = c.get("author", "مجهول")
                    author_obj = next((m for m in members_data if m.get("member") == author_name), {})
                    img_val = author_obj.get("img", "default.png")
                    avatar_src = self.get_cached_member_image(img_val)

                    def edit_comm(comment_item=c):
                        edit_field = ft.TextField(value=comment_item.get("content", ""), multiline=True, text_align="right", text_size=14, color=BLUE, border_color=ft.colors.BLUE_200)
                        def save_edit(e):
                            comment_item["content"] = edit_field.value.strip()
                            if self.db.is_connected and "id" in comment_item:
                                try:
                                    self.db.update_data("lecture_comments", comment_item.get("id"), {"content": comment_item["content"]})
                                except Exception:
                                    pass
                            self.set_cached_data_to_file("lecture_comments", comments_data)
                            self.page.dialog.open = False
                            self.safe_update()
                            load_comments()
                            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم تعديل التعليق بنجاح!", text_align="center"), bgcolor=DONE))
                        self.page.dialog = ft.AlertDialog(
                            title=ft.Text("تعديل التعليق", size=14, color=BLUE, text_align="center"),
                            content=edit_field,
                            actions=[
                                ft.ElevatedButton("إلغاء", on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update()),
                                ft.ElevatedButton("حفظ", bgcolor=PRIMARY, color="white", on_click=save_edit)
                            ],
                            actions_alignment=ft.MainAxisAlignment.CENTER,
                        )
                        self.page.dialog.open = True
                        self.safe_update()

                    def delete_comm(comment_item=c):
                        if comment_item in comments_data:
                            comments_data.remove(comment_item)
                        if self.db.is_connected and "id" in comment_item:
                            try:
                                self.db.delete_data("lecture_comments", comment_item.get("id"))
                            except Exception:
                                pass
                        self.set_cached_data_to_file("lecture_comments", comments_data)
                        load_comments()
                        self.safe_update()
                        self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم حذف التعليق", text_align="center"), bgcolor=DONE))

                    actions_row = ft.Row([], spacing=0)
                    if is_owner or is_admin:
                        actions_row.controls.extend([
                            ft.IconButton(ft.icons.EDIT, icon_size=16, icon_color=ft.colors.GREY_500, tooltip="تعديل", on_click=lambda e, ci=c: edit_comm(ci)),
                            ft.TextButton("×", tooltip="حذف", style=ft.ButtonStyle(color="grey"), on_click=lambda e, ci=c: delete_comm(ci))
                        ])

                    comments_column.controls.append(
                        ft.Container(
                            padding=20,
                            bgcolor=ft.colors.WHITE,
                            border_radius=8,
                            shadow=ft.BoxShadow(spread_radius=1, blur_radius=4, color=ft.colors.BLACK12),
                            content=ft.Column([
                                ft.Row([
                                    ft.Row([
                                        ft.Image(src=avatar_src, width=35, height=35, border_radius=20, fit=ft.ImageFit.COVER),
                                        ft.Text(author_name, color=PRIMARY, size=13)]),
                                        ft.Container(width=10, height=1),
                                    ft.Row([ft.Text(c.get("date", ""), size=10, color=ft.colors.GREY_600), actions_row], spacing=0)
                                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                ft.Text(c.get("content", ""), size=13, color="grey"),
                                ft.Text(f"التقييم: {c.get('rating', '')}", size=11, color=ft.colors.AMBER_800) if c.get("rating") else ft.Container()
                            ], spacing=4)
                        )
                    )
            try:
                self.safe_ctrl_update(comments_column)
            except Exception:
                self.safe_update()

        def submit_comment(e):
            if is_locked and not is_admin:
                self.page.show_snack_bar(ft.SnackBar(content=ft.Text("المحاضرة مقفلة، لا يمكن إضافة تعليق أو تقييم", text_align="center"), bgcolor=ft.colors.GREY_800))
                return
            if not self.current_user_name:
                self.open_login_dialog(e)
                return
            
            new_comm = comment_input.value.strip()
            selected_rating = rating_dropdown.value
            if not new_comm and not selected_rating:
                return

            comments_data = self.fetch_with_cache("lecture_comments", [])
            new_id = max([c.get("id", 0) for c in comments_data], default=0) + 1

            new_item = {
                "id": new_id,
                "lecture_id": lec_id,
                "author": self.current_user_name,
                "content": new_comm or "تقييم فقط",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "rating": selected_rating or ""
            }

            if self.db.is_connected:
                try:
                    self.db.insert_data("lecture_comments", new_item)
                except Exception:
                    pass

            comments_data.insert(0, new_item)
            self.set_cached_data_to_file("lecture_comments", comments_data)

            comment_input.value = ""
            rating_dropdown.value = None
            load_comments()
            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم إضافة تعليقك بنجاح", text_align="center"), bgcolor=DONE))
            self.safe_ctrl_update(comment_input)
            self.safe_ctrl_update(rating_dropdown)

        def auto_refresh_comments():
            # يعيد جلب التعليقات كل بضع ثوانٍ طالما المستخدم لا يزال في نفس الصفحة
            while view_state["active"]:
                time.sleep(6)
                if not view_state["active"]:
                    break
                try:
                    load_comments()
                except Exception:
                    pass

        load_comments()
        threading.Thread(target=auto_refresh_comments, daemon=True).start()

        attachment_section = ft.Container()
        if has_attachment:
            attachment_section = ft.TextButton(
            "الملخص",
                icon=ft.icons.NOTES,
                icon_color=ft.colors.TEAL_200,
                on_click=lambda e:self.open_summary_view()
            )

        locked_notice = ft.Container(
            content=ft.Row([ft.Icon(ft.icons.LOCK, color=ft.colors.RED_700, size=16), ft.Text("هذه المحاضرة مقفلة ولا يسمح بالتعليق أو التقييم", color=ft.colors.RED_700, size=12)], spacing=6),
            bgcolor=ft.colors.RED_50, padding=8, border_radius=6
        ) if is_locked else EMPTY

        admin_lecture_actions = ft.Container()
        if is_admin:
            def toggle_lock_lecture(e):
                nonlocal is_locked
                is_locked = not is_locked
                lecture_item["locked"] = "true" if is_locked else "false"
                if self.db.is_connected:
                    try:
                        self.db.update_data("lectures", lec_id, {"locked": lecture_item["locked"]})
                    except Exception:
                        pass
                all_lecs = self.fetch_with_cache("lectures", [])
                for l in all_lecs:
                    if l.get("id") == lec_id:
                        l["locked"] = lecture_item["locked"]
                self.set_cached_data_to_file("lectures", all_lecs)
                self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم تحديث حالة القفل للمحاضرة", text_align="center"), bgcolor=ft.colors.BLUE_700))
                self.open_lecture_detail_view(lecture_item)

            admin_lecture_actions = ft.Row([
                ft.IconButton(
                    icon=ft.icons.LOCK_OPEN if is_locked else ft.icons.LOCK,
                    icon_color=ft.colors.RED_300,
                    on_click=toggle_lock_lecture
                )
            ])

        completed_date_text = lecture_item.get("completed_at", "")
        date_display_str = ""
        if completed_date_text:
            date_display_str += f"إنتهت يوم: {completed_date_text}"
        
        detail_view = ft.View(
            f"/lecture/{lec_id}",
            controls=[
                ft.AppBar(title=ft.Text(lecture_item.get("title", ""), size=15, color="white"), leading=ft.IconButton(ft.icons.ARROW_BACK, on_click=go_back, icon_color="white"), bgcolor =BLUE),
                ft.ListView([
                    ft.Container(
                        padding=15,
                        content=ft.Column([
                            ft.Column([
                                ft.Text(f"المحاضر: {lecture_item.get('member_name', 'لم يحدد')}", size=14, weight=ft.FontWeight.BOLD, color=BLUE),
                                ft.Row([
                                    ft.Text(date_display_str, size=11, color=ft.colors.BLUE_700),
                                    ft.Text(f'- المقترح: {lecture_item.get("suggested_by", "")}', size=11, color=BLUE), attachment_section], spacing=5)], spacing=15),
                            ft.Divider(height=1, color=ft.colors.GREY_200),
                            locked_notice,
                            admin_lecture_actions,
                            EMPTY if is_locked and not is_admin else rating_dropdown,
                            EMPTY if is_locked and not is_admin else ft.Stack([comment_input,
                                    ft.IconButton(ft.icons.SEND,icon_color=BLUE, on_click=submit_comment, left=2, top=16, icon_size=15, bgcolor ="white", width=30, height=30)]),
                            ft.Text("التقييم والتعليقات", size=13, color=BLUE),
                            ft.Divider(height=10),
                            comments_column
                        ], spacing=12)
                    )
                ], expand=True)
            ]
        )
        self.page.views.append(detail_view)
        self.safe_update()

    def load_topics(self):
        def render_topics_list(topics):
            self.topics_list.controls.clear()
            all_topic_comments = self.get_cached_data_from_file("topic_comments", [])
            members_counter = self.get_cached_data_from_file("members", self.default_members)
            is_admin = self.is_current_user_admin()

            for item in topics:
                item["total"] = len(members_counter)
                title = item.get("title", "").lower()
                suggested = item.get("suggested_by", "").lower()
                if self.search_query and self.search_query not in title and self.search_query not in suggested:
                    continue
                
                top_id = item.get("id")
                actual_count = len([c for c in all_topic_comments if str(c.get("topic_id")) == str(top_id)])
                item["comments_count"] = actual_count

                def open_topic_detail(topic_item=item):
                    # علم للتحكم بحلقة التحديث التلقائي للتعليقات، يوقَف فور مغادرة الصفحة
                    view_state = {"active": True}

                    def go_back(e):
                        view_state["active"] = False
                        self.page.views.pop()
                        self.safe_update()

                    top_id = topic_item.get("id")
                    topic_title = topic_item.get("title", "")
                    is_admin = self.is_current_user_admin()
                    
                    comment_input = ft.TextField(label="أضف تعليقاً على المقترح...", border_radius=8, border_color=BLUE, label_style=ft.TextStyle(color=BLUE, size=13), color=BLUE, multiline=True, min_lines=1, max_lines=3, content_padding=20)
                    comments_column = ft.Column(spacing=8)
                    default_topic_comments = [{"id": 1, "topic_id": top_id, "author": topic_item.get("suggested_by", "عضو"), "content": "مقترح ممتاز ويستحق النقاش.", "date": "2026-08-20"}]

                    def load_topic_comments():
                        comments_data = self.fetch_with_cache("topic_comments", default_topic_comments)
                        filtered_comments = [c for c in comments_data if str(c.get("topic_id")) == str(top_id)]
                        members_data = self.fetch_with_cache("members", self.default_members)

                        comments_column.controls.clear()
                        
                        if not filtered_comments:
                            comments_column.controls.append(
                                ft.Container(
                                    content=ft.Text("لا توجد تعليقات", color=ft.colors.GREY_600, size=13),
                                    alignment=ft.alignment.center,
                                    padding=20
                                )
                            )
                        else:
                            for c in filtered_comments:
                                is_owner = self.current_user_name and c.get("author") == self.current_user_name
                                author_name = c.get("author", "مجهول")
                                author_obj = next((m for m in members_data if m.get("member") == author_name), {})
                                img_val = author_obj.get("img", "default.png")
                                avatar_src = self.get_cached_member_image(img_val)

                                def edit_topic_comm(comment_item=c):
                                    edit_field = ft.TextField(value=comment_item.get("content", ""), multiline=True, label="تعديل التعليق")
                                    def save_edit(e):
                                        new_content = edit_field.value.strip()
                                        comment_item["content"] = new_content
                                        if self.db.is_connected and "id" in comment_item:
                                            try:
                                                self.db.update_data("topic_comments", comment_item.get("id"), {"content": new_content})
                                            except Exception:
                                                pass
                                        self.set_cached_data_to_file("topic_comments", comments_data)
                                        self.page.dialog.open = False
                                        self.safe_update()
                                        load_topic_comments()
                                        self.load_topics()
                                        self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم تعديل التعليق بنجاح!")))
                                    
                                    self.page.dialog = ft.AlertDialog(
                                        title=ft.Text("تعديل التعليق"),
                                        content=edit_field,
                                        actions=[
                                            ft.ElevatedButton("إلغاء", on_click=lambda e: setattr(self.page.dialog, 'open', False) or self.safe_update()),
                                            ft.ElevatedButton("حفظ", bgcolor=PRIMARY, color="white", on_click=save_edit)
                                        ]
                                    )
                                    self.page.dialog.open = True
                                    self.safe_update()

                                def delete_topic_comm(comment_item=c):
                                    if comment_item in comments_data:
                                        comments_data.remove(comment_item)
                                    if self.db.is_connected and "id" in comment_item:
                                        try:
                                            self.db.delete_data("topic_comments", comment_item.get("id"))
                                        except Exception:
                                            pass
                                    self.set_cached_data_to_file("topic_comments", comments_data)
                                    load_topic_comments()
                                    self.load_topics()
                                    self.safe_update()
                                    self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم حذف التعليق", text_align="center"), bgcolor=DONE))

                                actions_row = ft.Row([], spacing=0)
                                if is_owner or is_admin:
                                    actions_row.controls.extend([
                                        ft.IconButton(ft.icons.EDIT, icon_size=16, icon_color=ft.colors.GREY_500, tooltip="تعديل", on_click=lambda e, ci=c: edit_topic_comm(ci)),
                                        ft.TextButton("×", style=ft.ButtonStyle(color="grey"), tooltip="حذف", on_click=lambda e, ci=c: delete_topic_comm(ci))
                                    ])

                                comments_column.controls.append(
                                    ft.Container(
                                        padding=20,
                                        bgcolor=ft.colors.WHITE,
                                        border_radius=8,
                                        shadow=ft.BoxShadow(spread_radius=1, blur_radius=4, color=ft.colors.BLACK12),
                                        content=ft.Column([
                                            ft.Row([
                                                ft.Row([
                                                    ft.Image(src=avatar_src, width=35, height=35, border_radius=20, fit=ft.ImageFit.COVER),
                                                    ft.Text(author_name, color=PRIMARY, size=13)]),
                                                ft.Container(width=10, height=1),
                                                ft.Row([ft.Text(c.get("date", ""), size=10, color=ft.colors.GREY_500), actions_row], spacing=0)
                                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                                            ft.Text(c.get("content", ""), size=13, color="grey")
                                        ], spacing=4)
                                    )
                                )
                        try:
                            self.safe_ctrl_update(comments_column)
                        except Exception:
                            self.safe_update()

                    def submit_topic_comment(e):
                        if not self.current_user_name:
                            self.open_login_dialog(e)
                            return
                        new_comm = comment_input.value.strip()
                        if not new_comm:
                            return

                        current_cached = self.fetch_with_cache("topic_comments", default_topic_comments)
                        new_id = max([c.get("id", 0) for c in current_cached], default=0) + 1
                        new_item = {
                            "id": new_id,
                            "topic_id": top_id,
                            "author": self.current_user_name,
                            "content": new_comm,
                            "date": datetime.now().strftime("%Y-%m-%d")
                        }

                        if self.db.is_connected:
                            try:
                                self.db.insert_data("topic_comments", new_item)
                            except Exception:
                                pass

                        current_cached.insert(0, new_item)
                        self.set_cached_data_to_file("topic_comments", current_cached)

                        comment_input.value = ""
                        load_topic_comments()
                        self.load_topics()  
                        self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم إضافة تعليقك بنجاح!", text_align="center"), bgcolor=DONE))

                    def auto_refresh_topic_comments():
                        # يعيد جلب تعليقات المقترح كل بضع ثوانٍ طالما المستخدم لا يزال في نفس الصفحة
                        while view_state["active"]:
                            time.sleep(6)
                            if not view_state["active"]:
                                break
                            try:
                                load_topic_comments()
                            except Exception:
                                pass

                    load_topic_comments()
                    threading.Thread(target=auto_refresh_topic_comments, daemon=True).start()

                    admin_topic_actions = ft.Container()
                    if is_admin:
                        def delete_topic_item(e):
                            topics = self.fetch_with_cache("topics", [])
                            topics = [t for t in topics if t.get("id") != top_id]
                            self.set_cached_data_to_file("topics", topics)
                            if self.db.is_connected:
                                try:
                                    self.db.delete_data("topics", top_id)
                                except Exception:
                                    pass
                            self.page.views.pop()
                            self.load_all_data()
                            self.safe_update()
                            self.page.show_snack_bar(ft.SnackBar(content=ft.Text("تم حذف المقترح بنجاح", text_align="center"), bgcolor=DONE))

                        admin_topic_actions = ft.Row([
                            ft.IconButton(icon=ft.icons.DELETE_FOREVER, icon_color=ft.colors.RED_300, on_click=delete_topic_item)
                        ])
                        
                    detail_view = ft.View(
                        f"/topic/{top_id}",
                        controls=[
                            ft.AppBar(title=ft.Text(topic_title, size=15, color="white"), leading=ft.IconButton(ft.icons.ARROW_BACK, on_click=go_back, icon_color="white"), bgcolor=BLUE),
                            ft.ListView([
                                ft.Container(
                                    padding=16,
                                    content=ft.Column([
                                        ft.Column([
                                            ft.Text(f"التصنيف: {topic_item.get('category', '')}", size=14, weight=ft.FontWeight.BOLD, color=ft.colors.BLUE_400),
                                            ft.Row([ft.Text(f"التاريخ: {topic_item.get('created_at')} - ", size=12, color=ft.colors.BLUE_400),
                                                ft.Text(f"المقترح: {topic_item.get('suggested_by', '')}", size=12, color=ft.colors.BLUE_400)], spacing=0)
                                        ], spacing=10),
                                        ft.Divider(),
                                        admin_topic_actions,
                                        ft.Stack([comment_input,
                                        ft.IconButton(ft.icons.SEND,icon_color=BLUE, on_click=submit_topic_comment, left=2, top=16, icon_size=15, bgcolor ="white", width=30, height=30)]),
                                        ft.Text("نقاشات الأعضاء حول المقترح", size=13, color=BLUE),
                                        ft.Divider(height=1, color=ft.colors.GREY_200),
                                        ft.Container(height=10),
                                        comments_column
                                    ], spacing=12)
                                )
                            ], expand=True)
                        ]
                    )
                    self.page.views.append(detail_view)
                    self.safe_update()

                self.topics_list.controls.append(
                    TopicCard(
                        item, 
                        is_admin=is_admin,
                        on_vote_click=self.handle_vote, 
                        on_click=open_topic_detail,
                        on_delete_click=self.handle_delete_topic,
                        on_edit_click=self.handle_edit_topic,
                        on_accept_click=self.handle_accept_topic
                    )
                )

            if not self.topics_list.controls:
                self.topics_list.controls.append(
                    ft.Container(content=ft.Text("لا توجد مقترحات", color=ft.colors.GREY_600), alignment=ft.alignment.center, padding=30)
                )
            self.safe_update()

        topics = self.fetch_with_cache("topics", self.default_topics, on_bg_updated=render_topics_list)
        render_topics_list(topics)

def main(page: ft.Page):
    def window_event(e):
    	if e.data == "close":
    		page.window_destroy()
    page.on_window_event = window_event
    def page_lifecycle_change(e):
    	if e.data == "resume":
    		page.update()
    page.on_app_lifecycle_change = page_lifecycle_change

    page.rtl = True
    page.fonts = {"font": "font/ar.ttf"}
    page.theme = ft.Theme(font_family="font", color_scheme=ft.ColorScheme(primary=ft.colors.INDIGO_400))
    ForumApp(page)

if __name__ == "__main__":
    ft.app(target=main, assets_dir="assets")
