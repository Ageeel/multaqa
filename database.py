import requests

class SupabaseManager:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip('/')
        self.key = key
        
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        
        self.is_connected = self.check_connection()

    def check_connection(self):
        try:
            response = requests.get(
                f"{self.url}/rest/v1/members?select=id&limit=1", 
                headers=self.headers, 
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Connection check failed: {e}")
            return False

    def fetch_data(self, table_name: str):
        try:
            response = requests.get(
                f"{self.url}/rest/v1/{table_name}?select=*", 
                headers=self.headers, 
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error fetching {table_name}: {response.text}")
                return []
        except Exception as e:
            print(f"Exception fetching {table_name}: {e}")
            return []

    def insert_data(self, table_name: str, data: dict):
        try:
            response = requests.post(
                f"{self.url}/rest/v1/{table_name}", 
                headers=self.headers, 
                json=data, 
                timeout=10
            )
            return response.status_code in [200, 201]
        except Exception as e:
            print(f"Exception inserting into {table_name}: {e}")
            return False

    def update_data(self, table_name: str, record_id, data: dict):
        try:
            response = requests.patch(
                f"{self.url}/rest/v1/{table_name}?id=eq.{record_id}", 
                headers=self.headers, 
                json=data, 
                timeout=10
            )
            if response.status_code in [200, 204]:
                return True
            # نطبع تفاصيل الخطأ الحقيقية من Supabase عشان تظهر في كونسول Pydroid
            print(f"[update_data] فشل تحديث {table_name} (id={record_id}) | status={response.status_code} | body={response.text}")
            return False
        except Exception as e:
            print(f"Exception updating {table_name}: {e}")
            return False

    def delete_data(self, table_name: str, record_id):
        try:
            response = requests.delete(
                f"{self.url}/rest/v1/{table_name}?id=eq.{record_id}", 
                headers=self.headers, 
                timeout=10
            )
            return response.status_code in [200, 204]
        except Exception as e:
            print(f"Exception deleting from {table_name}: {e}")
            return False

    def get_member_image(self, img_name):
        if not img_name:
            return f"{self.url}/storage/v1/object/public/members/default.png"
        return f"{self.url}/storage/v1/object/public/members/{img_name}"
