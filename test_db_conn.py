import asyncio
import asyncpg

async def test_conn():
    passwords = ["postgres", "", "root", "password", "admin", "123456"]
    for pwd in passwords:
        try:
            print(f"Testing password: '{pwd}'")
            conn = await asyncpg.connect(
                user='postgres',
                password=pwd,
                database='postgres',
                host='127.0.0.1',
                port=5432,
                timeout=2.0
            )
            print(f"✅ Success! Connected using password: '{pwd}'")
            await conn.close()
            return pwd
        except Exception as e:
            print(f"❌ Failed: {e}")
    print("Could not connect with any common default passwords.")
    return None

if __name__ == "__main__":
    asyncio.run(test_conn())
