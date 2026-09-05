import flet as ft

TITLE = ft.colors.BLUE_800
SUB_TITLE = ft.colors.BLUE_300
GREY = "#455A64"

# ==========================================
# LECTURE CARD COMPONENT CLASS
# ==========================================
class LectureCard(ft.Card):
    def __init__(self, item: dict, is_admin: bool, on_vote_click=None, on_click=None, on_delete_click=None, on_edit_click=None, on_assign_lecturer=None):
        super().__init__(
            elevation=2,
            shape=ft.RoundedRectangleBorder(radius=12)
        )
        self.item = item
        self.is_admin = is_admin
        self.on_vote_click = on_vote_click
        self.on_click = on_click
        self.on_delete_click = on_delete_click
        self.on_edit_click = on_edit_click
        self.on_assign_lecturer = on_assign_lecturer
        self.content = self.build_content()

    def admin_actions_button(self, item):
        SIZE: int = 16
        return ft.Row([
            ft.IconButton(
                "delete", 
                icon_color=ft.colors.RED_200, 
                icon_size=SIZE, 
                tooltip="حذف المحاضرة",
                on_click=lambda e: self.on_delete_click(self.item) if self.on_delete_click else None
            ),
            ft.IconButton(
                "person", 
                icon_color=ft.colors.BLUE_300, 
                icon_size=SIZE, 
                tooltip="تعيين محاضر",
                on_click=lambda e: self.on_assign_lecturer(self.item) if self.on_assign_lecturer else None
            ),
            ft.IconButton(
                "edit", 
                icon_color=ft.colors.BLUE_300, 
                icon_size=SIZE, 
                tooltip="تعديل المحاضرة",
                on_click=lambda e: self.on_edit_click(self.item) if self.on_edit_click else None
            )
        ], spacing=0)

    def build_content(self):
        return ft.Container(
            padding=16,
            bgcolor=ft.colors.WHITE,
            border_radius=12,
            ink=True,
            on_click=lambda e: self.on_click(self.item) if self.on_click else None,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text(self.item.get("type", "عام"), size=11, color=ft.colors.BLUE_800, weight=ft.FontWeight.BOLD),
                                bgcolor=ft.colors.BLUE_50,
                                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                border_radius=6
                            ),
                            self.admin_actions_button(self.item) if self.is_admin else ft.Container(visible=False),
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.icons.CALENDAR_TODAY, size=14, color=ft.colors.BLUE_300),
                                    ft.Text(self.item.get("date", ""), size=12, color=ft.colors.BLUE_300)
                                ],
                                spacing=4
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    ft.Divider(height=10, color=ft.colors.GREY_200),
                    ft.Text(self.item.get("title", ""), size=15, color=TITLE),
                    ft.Row(
                        controls=[
                            ft.Icon(ft.icons.PERSON_OUTLINE, size=16, color=SUB_TITLE),
                            ft.Text(f"المحاضر: {self.item.get('member_name', 'لم يحدد')}", size=13, color=SUB_TITLE)
                        ],
                        spacing=6
                    ),
                    ft.Row(
                        controls=[
                            ft.Icon(ft.icons.LIGHTBULB_OUTLINE, size=16, color=SUB_TITLE),
                            ft.Text(f"مقترح من: {self.item.get('suggested_by', '')}", size=12, color=SUB_TITLE)
                        ],
                        spacing=6
                    ),
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.icons.HOW_TO_VOTE, size=16, color=ft.colors.AMBER_700),
                                    ft.Text(f"الأصوات: {self.item.get('votes', 0)} من أصل  {self.item.get('total')}", size=12, color=ft.colors.AMBER_700)
                                ],
                                spacing=4
                            ),
                            ft.IconButton(
                                icon=ft.icons.THUMB_UP_ALT_OUTLINED,
                                icon_size=16,
                                icon_color=ft.colors.INDIGO_600,
                                tooltip="تصويت",
                                on_click=lambda e: self.on_vote_click(self.item, "lectures") if self.on_vote_click else None
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    )                  
                ],
                spacing=8
            )
        )


# ==========================================
# TOPIC CARD COMPONENT CLASS
# ==========================================
class TopicCard(ft.Card):
    def __init__(self, item: dict, is_admin: bool = False, on_vote_click=None, on_click=None, on_delete_click=None, on_edit_click=None, on_accept_click=None):
        super().__init__(
            elevation=2,
            shape=ft.RoundedRectangleBorder(radius=12)
        )
        self.item = item
        self.is_admin = is_admin
        self.on_vote_click = on_vote_click
        self.on_click = on_click
        self.on_delete_click = on_delete_click
        self.on_edit_click = on_edit_click
        self.on_accept_click = on_accept_click
        self.content = self.build_content()

    def admin_actions_button(self):
        SIZE: int = 16
        is_accepted = str(self.item.get("accepted", "false")).lower() in ["true", "1"]
        return ft.Row([
            ft.IconButton(
                "delete", 
                icon_color=ft.colors.RED_200, 
                icon_size=SIZE, 
                tooltip="حذف المقترح",
                on_click=lambda e: self.on_delete_click(self.item) if self.on_delete_click else None
            ),
            ft.IconButton(
                "edit", 
                icon_color=ft.colors.BLUE_300, 
                icon_size=SIZE, 
                tooltip="تعديل المقترح",
                on_click=lambda e: self.on_edit_click(self.item) if self.on_edit_click else None
            ),
            ft.IconButton(
                "book",
                icon_color=ft.colors.BLUE_300 if not is_accepted else ft.colors.GREY_400, 
                icon_size=SIZE, 
                disabled=is_accepted,
                tooltip="نقل إلى المحاضرات القادمة",
                on_click=lambda e: self.on_accept_click(self.item) if self.on_accept_click else None
            ) if not is_accepted else ft.Container(height=0, width=0, visible=False)
        ], spacing=0)

    def build_content(self):
        is_accepted = str(self.item.get("accepted", "false")).lower() in ["true", "1"]
        
        status_badge = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.icons.CHECK_CIRCLE, size=14, color=ft.colors.TEAL_500),
                    ft.Text("تم القبول", size=11, color=ft.colors.TEAL_500, weight=ft.FontWeight.BOLD)
                ],
                spacing=4
            ),
            bgcolor=ft.colors.GREEN_50,
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=6
        ) if is_accepted else ft.Container(
            content=ft.Text("قيد الإنتظار", size=10, color=ft.colors.WHITE),
            bgcolor=ft.colors.ORANGE_400,
            padding=ft.padding.symmetric(horizontal=8, vertical=3),
            border_radius=4
        )

        proposal_date = self.item.get("created_at", "")
        comments_count = self.item.get("comments_count", 0)

        return ft.Container(
            padding=16,
            bgcolor=ft.colors.WHITE,
            border_radius=12,
            ink=True,
            on_click=lambda e: self.on_click(self.item) if self.on_click else None,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text(self.item.get("category", "عام"), size=11, color=ft.colors.BLUE_800, weight=ft.FontWeight.BOLD),
                                bgcolor=ft.colors.BLUE_50,
                                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                                border_radius=6
                            ),
                            self.admin_actions_button() if self.is_admin else ft.Container(visible=False),
                            status_badge,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    ft.Divider(height=10, color=ft.colors.GREY_200),
                    ft.Text(self.item.get("title", ""), size=15, color=TITLE),
                    ft.Row(
                        controls=[
                            ft.Icon(ft.icons.LIGHTBULB_OUTLINE, size=16, color=SUB_TITLE),
                            ft.Text(f"مقترح بواسطة: {self.item.get('suggested_by', '')}", size=13, color=SUB_TITLE)
                        ],
                        spacing=6
                    ),
                    ft.Row(
                        controls=[
                            ft.Icon(ft.icons.CALENDAR_MONTH, size=14, color=SUB_TITLE),
                            ft.Text(f"التاريخ: {proposal_date}", size=11, color=SUB_TITLE)
                        ],
                        spacing=4
                    ),
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.icons.HOW_TO_VOTE, size=16, color=ft.colors.AMBER_700),
                                    ft.Text(f"الأصوات: {self.item.get('votes', 0)} من أصل {self.item.get('total')}", size=12, color=ft.colors.AMBER_700)
                                ],
                                spacing=4
                            ),
                            ft.Row(
                                controls=[
                                    ft.Icon(ft.icons.COMMENT, size=14, color=ft.colors.BLUE_700),
                                    ft.Text(f"التعليقات: {comments_count}", size=12, color=ft.colors.BLUE_700)
                                ],
                                spacing=4
                            ),
                            ft.IconButton(
                                icon=ft.icons.THUMB_UP_ALT_OUTLINED,
                                icon_size=16,
                                icon_color=ft.colors.INDIGO_600,
                                tooltip="تصويت للمقترح",
                                on_click=lambda e: self.on_vote_click(self.item, "topics") if self.on_vote_click else None
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    )
                ],
                spacing=8
            )
        )


# ==========================================
# COMMENT CARD COMPONENT CLASS
# ==========================================
class CommentCard(ft.Card):
    def __init__(self, comment: dict, current_user: str, on_edit=None, on_delete=None):
        super().__init__(
            elevation=1,
            shape=ft.RoundedRectangleBorder(radius=10)
        )
        self.comment = comment
        self.current_user = current_user
        self.on_edit = on_edit
        self.on_delete = on_delete
        self.content = self.build_content()

    def build_content(self):
        author = self.comment.get("author", "مستخدم")
        avatar_src = self.comment.get("img", "default.png")
        body = self.comment.get("content", "")
        date_str = self.comment.get("date", "")
        rating = self.comment.get("rating", "")

        is_owner = (author == self.current_user)

        actions_row = ft.Row(spacing=0)
        if is_owner:
            actions_row.controls.extend([
                ft.IconButton(
                    icon=ft.icons.EDIT,
                    icon_size=14,
                    icon_color=ft.colors.BLUE_700,
                    tooltip="تعديل",
                    on_click=lambda e: self.on_edit(self.comment) if self.on_edit else None
                ),
                ft.IconButton(
                    icon=ft.icons.DELETE,
                    icon_size=14,
                    icon_color=ft.colors.RED_700,
                    tooltip="حذف",
                    on_click=lambda e: self.on_delete(self.comment) if self.on_delete else None
                )
            ])

        rating_badge = ft.Container()
        if rating:
            rating_badge = ft.Container(
                content=ft.Text(f"التقييم: {rating}", size=10, color=ft.colors.INDIGO_900),
                bgcolor=ft.colors.INDIGO_50,
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=4
            )

        return ft.Container(
            padding=10,
            bgcolor=ft.colors.WHITE,
            border_radius=10,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.CircleAvatar(content=ft.Image(src=avatar_src), radius=16, bgcolor=ft.colors.PURPLE_100),
                                    ft.Text(author, size=13, weight=ft.FontWeight.BOLD, color=TITLE),
                                ],
                                spacing=8
                            ),
                            ft.Row(
                                controls=[rating_badge, actions_row],
                                spacing=4
                            )
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                    ),
                    ft.Text(body, size=13, color=GREY),
                    ft.Row(
                        controls=[
                            ft.Icon(ft.icons.ACCESS_TIME, size=12, color=ft.colors.GREY_500),
                            ft.Text(date_str, size=10, color=ft.colors.GREY_500)
                        ],
                        spacing=4
                    )
                ],
                spacing=6
            )
        )
