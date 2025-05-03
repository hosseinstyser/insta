import os
import re
import requests
from urllib.parse import urlparse
import instaloader
from typing import Optional, Tuple, List
from telegram import Update, InputMediaPhoto, InputMediaVideo
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import logging
from dotenv import load_dotenv

# بارگذاری متغیرهای محیطی
load_dotenv()

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class InstagramDownloader:
    def __init__(self):
        self.loader = instaloader.Instaloader(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            request_timeout=120,
            sleep=True,
            max_connection_attempts=2,
            save_metadata=False,
            download_comments=False,
            compress_json=False,
            download_geotags=False,
            download_video_thumbnails=False,
            post_metadata_txt_pattern=""
        )
        
        # تنظیمات هدرها
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        
        # تنظیمات session
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def sanitize_filename(self, filename: str) -> str:
        """حذف کاراکترهای غیرمجاز از نام فایل"""
        return re.sub(r'[<>:"/\\|?*]', '', filename)

    def login(self, username: str, password: str) -> bool:
        """ورود به حساب اینستاگرام"""
        try:
            self.loader.context.login(username, password)
            self.loader.save_session_to_file()
            logger.info("ورود موفقیت‌آمیز بود")
            return True
        except Exception as e:
            logger.error(f"خطا در ورود: {str(e)}")
            return False

    def download_media(self, url: str, filename: str = None) -> Optional[str]:
        """دانلود مدیا از URL"""
        try:
            response = self.session.get(url, stream=True, timeout=60)
            response.raise_for_status()

            if not filename:
                filename = os.path.basename(urlparse(url).path)

            filename = self.sanitize_filename(filename)
            
            if not os.path.splitext(filename)[1]:
                if 'image' in response.headers.get('content-type', ''):
                    filename += '.jpg'
                elif 'video' in response.headers.get('content-type', ''):
                    filename += '.mp4'

            temp_dir = os.path.join(os.getcwd(), 'temp_downloads')
            os.makedirs(temp_dir, exist_ok=True)
            save_path = os.path.join(temp_dir, filename)

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)

            logger.info(f"دانلود موفق: {save_path}")
            return save_path
        except Exception as e:
            logger.error(f"خطا در دانلود: {e}")
            return None

    def get_shortcode(self, url: str) -> str:
        """استخراج shortcode از URL"""
        pattern = r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv)/([^/?#&]+)'
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        raise ValueError("لینک نامعتبر")

    def get_post_info(self, url: str) -> Tuple[List[Tuple[str, str, str]], str]:
        """دریافت اطلاعات پست"""
        try:
            shortcode = self.get_shortcode(url)
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
            
            media_list = []
            caption = post.caption if post.caption else ""
            
            if post.typename == 'GraphSidecar':
                for idx, node in enumerate(post.get_sidecar_nodes(), start=1):
                    if node.is_video:
                        media_url = node.video_url
                        media_type = 'video'
                        ext = '.mp4'
                    else:
                        media_url = node.display_url
                        media_type = 'photo'
                        ext = '.jpg'
                    
                    filename = f"{post.owner_username}_post_{post.shortcode}_{idx}{ext}"
                    media_list.append((media_url, media_type, filename))
            else:
                if post.is_video:
                    media_url = post.video_url
                    media_type = 'video'
                    ext = '.mp4'
                else:
                    media_url = post.url
                    media_type = 'photo'
                    ext = '.jpg'
                
                filename = f"{post.owner_username}_post_{post.shortcode}{ext}"
                media_list.append((media_url, media_type, filename))
            
            return media_list, caption
        except Exception as e:
            logger.error(f"خطا در دریافت اطلاعات: {e}")
            return [], ""

class TelegramBot:
    def __init__(self, token: str, insta_downloader: InstagramDownloader):
        self.token = token
        self.insta_downloader = insta_downloader
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        # ثبت هندلرها
        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(CommandHandler("help", self.help))
        self.dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), self.handle_message))

    def start(self, update: Update, context: CallbackContext):
        """هندلر دستور /start"""
        welcome_message = """
        🤖 ربات دانلودر اینستاگرام 🤖

        لطفا لینک پست، ریلس، یا IGTV اینستاگرام را ارسال کنید.
        """
        update.message.reply_text(welcome_message)

    def help(self, update: Update, context: CallbackContext):
        """هندلر دستور /help"""
        help_message = """
        📚 راهنمای استفاده:
        1. لینک پست اینستاگرام را ارسال کنید
        2. ربات محتوا را دانلود می‌کند
        """
        update.message.reply_text(help_message)

    def is_valid_instagram_url(self, url: str) -> bool:
        """بررسی معتبر بودن URL"""
        patterns = [
            r'https?://(www\.)?instagram\.com/p/',
            r'https?://(www\.)?instagram\.com/reel/',
            r'https?://(www\.)?instagram\.com/tv/'
        ]
        return any(re.search(pattern, url) for pattern in patterns)

    def handle_message(self, update: Update, context: CallbackContext):
        """پردازش پیام کاربر"""
        text = update.message.text
        
        if not self.is_valid_instagram_url(text):
            update.message.reply_text("لطفا لینک معتبر ارسال کنید.")
            return
        
        try:
            update.message.reply_text("⏳ در حال پردازش...")
            
            media_list, caption = self.insta_downloader.get_post_info(text)
            
            if not media_list:
                update.message.reply_text("❌ خطا در دریافت محتوا")
                return
            
            downloaded_files = []
            for media_url, media_type, filename in media_list:
                file_path = self.insta_downloader.download_media(media_url, filename)
                if file_path:
                    downloaded_files.append((file_path, media_type))
            
            self.send_media(update, downloaded_files, caption)
            
        except Exception as e:
            logger.error(f"خطا: {e}")
            update.message.reply_text(f"❌ خطا: {str(e)}")
        finally:
            self.cleanup_files(downloaded_files)

    def send_media(self, update: Update, files: List[Tuple[str, str]], caption: str = ""):
        """ارسال مدیا به کاربر"""
        if len(files) == 1:
            file_path, media_type = files[0]
            try:
                with open(file_path, 'rb') as f:
                    if media_type == 'photo':
                        update.message.reply_photo(f, caption=caption[:1000])
                    else:
                        update.message.reply_video(f, caption=caption[:1000])
            except Exception as e:
                logger.error(f"خطا در ارسال: {e}")
        else:
            media_group = []
            for idx, (file_path, media_type) in enumerate(files):
                try:
                    with open(file_path, 'rb') as f:
                        if media_type == 'photo':
                            media = InputMediaPhoto(f, caption=caption[:1000] if idx == 0 else None)
                        else:
                            media = InputMediaVideo(f, caption=caption[:1000] if idx == 0 else None)
                        media_group.append(media)
                except Exception as e:
                    logger.error(f"خطا در آماده‌سازی مدیا: {e}")
            
            if media_group:
                try:
                    update.message.reply_media_group(media=media_group)
                except Exception as e:
                    logger.error(f"خطا در ارسال گروهی: {e}")

    def cleanup_files(self, files: List[Tuple[str, str]]):
        """حذف فایل‌های موقت"""
        for file_path, _ in files or []:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"خطا در حذف فایل: {e}")

    def start_bot(self):
        """شروع بات"""
        logger.info("ربات فعال شد")
        self.updater.start_polling()
        self.updater.idle()

def main():
    # تنظیمات    
    # os.environ['TELEGRAM_TOKEN'] = "7732534464:AAG-qNiJiAEz5F2-D4Y_6fqqw753bzzFntc"
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '7732534464:AAG-qNiJiAEz5F2-D4Y_6fqqw753bzzFntc')
    INSTA_USERNAME = os.getenv('INSTA_USERNAME')
    INSTA_PASSWORD = os.getenv('INSTA_PASSWORD')
    
    if not TELEGRAM_TOKEN:
        logger.error("توکن تلگرام یافت نشد")
        return
    
    # ایجاد دانلودر
    downloader = InstagramDownloader()
    if INSTA_USERNAME and INSTA_PASSWORD:
        downloader.login(INSTA_USERNAME, INSTA_PASSWORD)
    
    # شروع بات
    bot = TelegramBot(TELEGRAM_TOKEN, downloader)
    bot.start_bot()

if __name__ == '__main__':
    main()
