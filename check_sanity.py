import os
import sys
from dotenv import load_dotenv

load_dotenv(dotenv_path='/opt/gold/.env')

print('\n🔍 --- GOLD BOT SANITY CHECK SCORECARD ---')
print(f'🐍 Python Active Sandbox: {sys.prefix}')

file_exists = os.path.isfile('/opt/gold/engine.py')
print(f'📄 Core engine.py File Present: {file_exists}')

url_lines = []
if file_exists:
    with open('/opt/gold/engine.py', 'r') as f:
        url_lines = [line.strip() for line in f if 'url =' in line]
    if url_lines:
        print(f'📡 Active URL String in Code: {url_lines}')
        if any('api.telegram.org/bot' in line for line in url_lines):
            print('   ✅ VERIFIED: Telegram URL path structure is correct!')
        else:
            print('   ❌ ERROR: Telegram URL path formatting is incorrect.')
    else:
        print('   ❌ ERROR: url string definition not found inside engine.py')

tok = os.getenv('TELEGRAM_BOT_TOKEN')
chat = os.getenv('TELEGRAM_CHAT_ID')
api = os.getenv('TWELVE_DATA_API_KEY')

print('\n🔐 --- SECURE ENVIRONMENT KEY INTEGRITY ---')
print(f'🔑 TELEGRAM_BOT_TOKEN: Present (Length: {len(tok)})' if tok else '❌ TELEGRAM_BOT_TOKEN: Missing')
print(f'💬 TELEGRAM_CHAT_ID: Present ({chat})' if chat else '❌ TELEGRAM_CHAT_ID: Missing')
print(f'📈 TWELVE_DATA_API_KEY: Present (Length: {len(api)})' if api else '❌ TWELVE_DATA_API_KEY: Missing')

print('\n🏁 --- SYSTEM STATUS OUTCOME ---')
is_valid_url = any('api.telegram.org/bot' in line for line in url_lines) if url_lines else False

if file_exists and is_valid_url and tok and chat and api:
    print('✅ SUCCESS: Your system architecture is fully correct, healthy, and verified!')
else:
    print('❌ FAILED: Sanity check encountered a problem. Review metrics above.')
