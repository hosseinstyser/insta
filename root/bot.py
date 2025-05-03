import os
import re
import time
import random
import requests
import instaloader
from urllib.parse import urlparse
from typing import Optional, Tuple, List
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import logging
from dotenv import load_dotenv

# تنظیمات پایه
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class InstagramDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.setup_instaloader()
        self.setup_headers()
        self.insta_username = None
        self.insta_password = None

    def setup_instaloader(self):
        """تنظیمات اولیه instaloader"""
        self.loader = instaloader.Instaloader(
            sleep=True,
            request_timeout=120,
            max_connection_attempts=2,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            save_metadata=False,
            download_comments=False
        )

    def setup_headers(self):
        """تنظیمات هدرهای درخواست"""
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-IG-App-ID': '936619743392459'
        }
        self.session.headers.update(self.headers)
        self.loader.context._session.headers.update(self.headers)

    def login(self, username: str, password: str) -> bool:
        """ورود به اینستاگرام با مدیریت خطاها"""
        try:
            self.insta_username = username
            self.insta_password = password
            self.loader.context.login(username, password)
            self.loader.save_session_to_file()
            logger.info("ورود با موفقیت انجام شد")
            return True
        except Exception as e:
            logger.error(f"خطا در ورود: {str(e)}")
            return False

    def get_post_info(self, url: str) -> Tuple[List[Tuple[str, str, str]], str]:
        """دریافت اطلاعات پست با مدیریت خطاهای 401"""
        try:
            shortcode = self.extract_shortcode(url)
            
            # تاخیر تصادفی برای جلوگیری از بلاک
            time.sleep(random.uniform(1, 3))
            
            try:
                post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
            except Exception as e:
                if "401" in str(e) and self.insta_username and self.insta_password:
                    logger.warning("جلسه منقضی شده، تلاش مجدد با لاگین جدید...")
                    self.login(self.insta_username, self.insta_password)
                    post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
                else:
                    raise

            return self.process_post_content(post)
            
        except Exception as e:
            logger.error(f"خطا در دریافت پست: {str(e)}")
            return [], f"خطا: {str(e)}"

    def extract_shortcode(self, url: str) -> str:
        """استخراج shortcode از URL"""
        patterns = [
            r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv)/([^/?#&]+)',
            r'(?:https?://)?(?:www\.)?instagram\.com/reels/([^/?#&]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        raise ValueError("لینک اینستاگرام نامعتبر است")

    def process_post_content(self, post) -> Tuple[List[Tuple[str, str, str]], str]:
        """پردازش محتوای پست"""
        media_list = []
        caption = post.caption if post.caption else ""
        
        if post.typename == 'GraphSidecar':
            for idx, node in enumerate(post.get_sidecar_nodes(), start=1):
                media_type = 'video' if node.is_video else 'photo'
                media_url = node.video_url if node.is_video else node.display_url
                filename = f"{post.shortcode}_{idx}.{'mp4' if node.is_video else 'jpg'}"
                media_list.append((media_url, media_type, filename))
        else:
            media_type = 'video' if post.is_video else 'photo'
            media_url = post.video_url if post.is_video else post.url
            filename = f"{post.shortcode}.{'mp4' if post.is_video else 'jpg'}"
            media_list.append((media_url, media_type, filename))
        
        return media_list, caption

    def download_media(self, url: str, filename: str) -> Optional[str]:
        """دانلود مدیا با مدیریت خطاها"""
        try:
            response = self.session.get(url, stream=True, timeout=30)
            response.raise_for_status()

            os.makedirs('temp_downloads', exist_ok=True)
            filepath = os.path.join('temp_downloads', filename)

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)

            return filepath
        except Exception as e:
            logger.error(f"خطا در دانلود مدیا: {str(e)}")
            return None

class InstagramBot:
    def __init__(self, token: str):
        self.token = token
        self.downloader = InstagramDownloader()
        self.setup_bot()

    def setup_bot(self):
        """تنظیمات اولیه بات"""
        self.updater = Updater(token=self.token, use_context=True)
        dp = self.updater.dispatcher
        
        dp.add_handler(CommandHandler("start", self.start))
        dp.add_handler(CommandHandler("help", self.help))
        dp.add_handler(MessageHandler(Filters.text & ~Filters.command, self.handle_message))
        
        dp.add_error_handler(self.error_handler)

    def start(self, update: Update, context: CallbackContext):
        """دستور /start"""
        update.message.reply_text(
            "🤖 ربات دانلود اینستاگرام\n\n"
            "لینک پست، ریلس یا IGTV اینستاگرام را ارسال کنید."
        )

    def help(self, update: Update, context: CallbackContext):
        """دستور /help"""
        update.message.reply_text(
            "📚 راهنمای استفاده:\n"
            "1. لینک پست اینستاگرام را ارسال کنید\n"
            "2. ربات محتوا را دانلود و ارسال می‌کند\n\n"
            "مثال لینک معتبر:\n"
            "https://www.instagram.com/p/Cabcdef/"
        )

    def handle_message(self, update: Update, context: CallbackContext):
        """پردازش پیام کاربر"""
        url = update.message.text.strip()
        
        if not self.is_valid_url(url):
            update.message.reply_text("⚠️ لینک نامعتبر! لطفا یک لینک معتبر اینستاگرام ارسال کنید.")
            return
        
        try:
            update.message.reply_text("🔍 در حال پردازش لینک...")
            
            media_list, caption = self.downloader.get_post_info(url)
            if not media_list:
                update.message.reply_text("❌ محتوایی برای دانلود یافت نشد")
                return
            
            downloaded_files = []
            for media_url, media_type, filename in media_list:
                filepath = self.downloader.download_media(media_url, filename)
                if filepath:
                    downloaded_files.append((filepath, media_type))
            
            self.send_media(update, downloaded_files, caption)
            
        except Exception as e:
            logger.error(f"خطا در پردازش: {str(e)}")
            update.message.reply_text(f"❌ خطا: {str(e)}")
        finally:
            self.cleanup_files(downloaded_files if 'downloaded_files' in locals() else [])

    def is_valid_url(self, url: str) -> bool:
        """بررسی معتبر بودن URL"""
        patterns = [
            r'https?://(www\.)?instagram\.com/p/',
            r'https?://(www\.)?instagram\.com/reel/',
            r'https?://(www\.)?instagram\.com/tv/',
            r'https?://(www\.)?instagram\.com/reels/'
        ]
        return any(re.search(pattern, url) for pattern in patterns)

    def send_media(self, update: Update, files: List[Tuple[str, str]], caption: str):
        """ارسال مدیا به کاربر"""
        if not files:
            return
            
        try:
            if len(files) == 1:
                self.send_single_media(update, files[0], caption)
            else:
                self.send_media_group(update, files, caption)
        except Exception as e:
            logger.error(f"خطا در ارسال مدیا: {str(e)}")
            update.message.reply_text("❌ خطا در ارسال محتوا")

    def send_single_media(self, update: Update, file: Tuple[str, str], caption: str):
        """ارسال تک مدیا"""
        filepath, media_type = file
        try:
            with open(filepath, 'rb') as f:
                if media_type == 'photo':
                    update.message.reply_photo(f, caption=caption[:1000])
                else:
                    update.message.reply_video(f, caption=caption[:1000], supports_streaming=True)
        except Exception as e:
            raise Exception(f"ارسال تک مدیا ناموفق: {str(e)}")

    def send_media_group(self, update: Update, files: List[Tuple[str, str]], caption: str):
        """ارسال گروه مدیا"""
        media_group = []
        for idx, (filepath, media_type) in enumerate(files):
            try:
                with open(filepath, 'rb') as f:
                    if media_type == 'photo':
                        media = InputMediaPhoto(f, caption=caption[:1000] if idx == 0 else None)
                    else:
                        media = InputMediaVideo(f, caption=caption[:1000] if idx == 0 else None)
                    media_group.append(media)
            except Exception as e:
                logger.error(f"خطا در آماده‌سازی مدیا {idx}: {str(e)}")
                continue
        
        if media_group:
            try:
                update.message.reply_media_group(media_group)
            except Exception as e:
                raise Exception(f"ارسال گروه مدیا ناموفق: {str(e)}")

    def cleanup_files(self, files: List[Tuple[str, str]]):
        """حذف فایل‌های موقت"""
        for filepath, _ in files:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                logger.error(f"خطا در حذف فایل {filepath}: {str(e)}")

    def error_handler(self, update: Update, context: CallbackContext):
        """مدیریت خطاهای بات"""
        logger.error(f"خطای بات: {context.error}")
        if update and update.message:
            update.message.reply_text("⚠️ خطای داخلی رخ داده است. لطفا بعدا تلاش کنید.")

    def run(self):
        """اجرای بات"""
        logger.info("ربات در حال اجرا...")
        self.updater.start_polling()
        self.updater.idle()

def main():
    # دریافت تنظیمات
    TELEGRAM_TOKEN = os.getenv('7732534464:AAG-qNiJiAEz5F2-D4Y_6fqqw753bzzFntc')
    TELEGRAM_TOKEN = ('7732534464:AAG-qNiJiAEz5F2-D4Y_6fqqw753bzzFntc')
    INSTA_USERNAME = os.getenv('INSTA_USERNAME')
    INSTA_PASSWORD = os.getenv('INSTA_PASSWORD')
    
    if not TELEGRAM_TOKEN:
        logger.error("توکن تلگرام تنظیم نشده است!")
        return
    
    # ایجاد و راه‌اندازی بات
    bot = InstagramBot(TELEGRAM_TOKEN)
    
    # ورود به اینستاگرام اگر اطلاعات وجود دارد
    if INSTA_USERNAME and INSTA_PASSWORD:
        if not bot.downloader.login(INSTA_USERNAME, INSTA_PASSWORD):
            logger.warning("ورود به اینستاگرام ناموفق بود - ادامه با دسترسی عمومی")
    
    bot.run()

if __name__ == '__main__':
    main()
