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
        
        # تنظیمات پیشرفته session
        self.loader.context._session.headers.update({
            'X-IG-App-ID': '936619743392459',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        })
        
        # تنظیمات requests session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        })

    def login(self, username: str, password: str) -> bool:
        """ورود به حساب اینستاگرام با احراز هویت دو مرحله‌ای"""
        try:
            self.loader.context.login(username, password)
            # ذخیره session برای استفاده بعدی
            self.loader.save_session_to_file()
            logger.info("ورود به اینستاگرام موفقیت‌آمیز بود")
            return True
        except Exception as e:
            logger.error(f"خطا در ورود: {str(e)}")
            # راهکار جایگزین برای احراز هویت دو مرحله‌ای
            if "two-factor" in str(e):
                return self._handle_two_factor(username, password)
            return False

    def _handle_two_factor(self, username: str, password: str) -> bool:
        """مدیریت احراز هویت دو مرحله‌ای"""
        try:
            from instaloader import TwoFactorAuthRequiredException
            code = input("کد احراز هویت دو مرحله‌ای را وارد کنید: ")
            self.loader.context.two_factor_login(code)
            self.loader.save_session_to_file()
            return True
        except Exception as e:
            logger.error(f"خطا در احراز دو مرحله‌ای: {str(e)}")
            return False

def download_media(self, url: str, filename: str = None) -> Optional[str]:
    """دانلود مدیا از URL"""
    try:
        response = self.session.get(url, headers=self.headers, stream=True, timeout=60)
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

        logger.info(f"مدیا با موفقیت دانلود شد: {save_path}")
        return save_path
    except Exception as e:
        logger.error(f"خطا در دانلود مدیا: {e}")
        return None
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
            logger.error(f"خطا در دریافت اطلاعات پست: {e}")
            return [], ""

    def get_shortcode(self, url: str) -> str:
        """استخراج shortcode از URL"""
        pattern = r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv)/([^/?#&]+)'
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        raise ValueError("لینک اینستاگرام نامعتبر است.")

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

        دستورات:
        /start - نمایش این پیام
        /help - راهنمای استفاده
        
        نکات:
        - لینک باید مستقیم از اینستاگرام باشد
        - برای پست‌های خصوصی، ربات باید با حساب اینستاگرام شما لاگین کرده باشد
        """
        update.message.reply_text(welcome_message)

    def help(self, update: Update, context: CallbackContext):
        """هندلر دستور /help"""
        help_message = """
        📚 راهنمای استفاده از ربات:
        
        1. لینک پست اینستاگرام را برای ربات ارسال کنید
        2. ربات محتوای پست را دانلود و برای شما ارسال می‌کند
        
        انواع لینک‌های پشتیبانی شده:
        - پست عکس/فیلم (instagram.com/p/)
        - ریلس (instagram.com/reel/)
        - IGTV (instagram.com/tv/)
        """
        update.message.reply_text(help_message)

    def handle_message(self, update: Update, context: CallbackContext):
        """هندلر پیام‌های کاربر"""
        text = update.message.text
        chat_id = update.message.chat_id
        
        if not self.is_valid_instagram_url(text):
            update.message.reply_text("لطفا یک لینک معتبر اینستاگرام ارسال کنید.\nمثال:\nhttps://www.instagram.com/p/Cabcdef/")
            return
        
        try:
            update.message.reply_text("⏳ در حال پردازش لینک... لطفا صبر کنید.")
            
            media_list, caption = self.insta_downloader.get_post_info(text)
            
            if not media_list:
                update.message.reply_text("❌ خطا در دریافت محتوا. ممکن است پست خصوصی باشد یا لینک نامعتبر است.")
                return
            
            try:
                downloaded_files = []
                for media_url, media_type, filename in media_list:
                    file_path = self.insta_downloader.download_media(media_url, filename)
                    if file_path:
                        downloaded_files.append((file_path, media_type))
                
                if not downloaded_files:
                    update.message.reply_text("❌ خطا در دانلود محتوا")
                    return
                
                self.send_media(update, downloaded_files, caption)
                
            finally:
                self.cleanup_files(downloaded_files)
        
        except Exception as e:
            logger.error(f"خطا در پردازش لینک: {e}")
            update.message.reply_text(f"❌ خطا در پردازش لینک: {str(e)}")

    def is_valid_instagram_url(self, url: str) -> bool:
        """بررسی معتبر بودن URL اینستاگرام"""
        patterns = [
            r'https?://(www\.)?instagram\.com/p/',
            r'https?://(www\.)?instagram\.com/reel/',
            r'https?://(www\.)?instagram\.com/tv/',
            r'https?://(www\.)?instagram\.com/reels/'
        ]
        return any(re.search(pattern, url) for pattern in patterns)

    def send_media(self, update: Update, files: List[Tuple[str, str]], caption: str = ""):
        """ارسال مدیا به کاربر"""
        if len(files) == 1:
            file_path, media_type = files[0]
            try:
                with open(file_path, 'rb') as media_file:
                    if media_type == 'photo':
                        update.message.reply_photo(
                            photo=media_file,
                            caption=caption[:1000] if caption else None,
                            parse_mode='HTML'
                        )
                    else:
                        update.message.reply_video(
                            video=media_file,
                            caption=caption[:1000] if caption else None,
                            supports_streaming=True,
                            parse_mode='HTML'
                        )
            except Exception as e:
                logger.error(f"خطا در ارسال مدیا: {e}")
                update.message.reply_text("❌ خطا در ارسال محتوا")
        else:
            media_group = []
            for idx, (file_path, media_type) in enumerate(files):
                try:
                    with open(file_path, 'rb') as media_file:
                        if media_type == 'photo':
                            media = InputMediaPhoto(
                                media=media_file,
                                caption=caption[:1000] if idx == 0 and caption else None,
                                parse_mode='HTML'
                            )
                        else:
                            media = InputMediaVideo(
                                media=media_file,
                                caption=caption[:1000] if idx == 0 and caption else None,
                                parse_mode='HTML'
                            )
                        media_group.append(media)
                except Exception as e:
                    logger.error(f"خطا در آماده‌سازی مدیا گروهی: {e}")
                    continue
            
            if media_group:
                try:
                    update.message.reply_media_group(media=media_group)
                except Exception as e:
                    logger.error(f"خطا در ارسال مدیا گروهی: {e}")
                    update.message.reply_text("❌ خطا در ارسال محتوای چندگانه")

    def cleanup_files(self, files: List[Tuple[str, str]]):
        """پاکسازی فایل‌های موقت"""
        for file_path, _ in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"فایل موقت حذف شد: {file_path}")
            except Exception as e:
                logger.error(f"خطا در حذف فایل موقت {file_path}: {e}")

    def start_bot(self):
        """شروع کار بات"""
        logger.info("ربات در حال اجرا...")
        self.updater.start_polling()
        self.updater.idle()

def main():
    # دریافت تنظیمات از متغیرهای محیطی    
    os.environ['TELEGRAM_TOKEN'] = "7732534464:AAG-qNiJiAEz5F2-D4Y_6fqqw753bzzFntc"
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    INSTA_USERNAME = os.getenv('INSTA_USERNAME')
    INSTA_PASSWORD = os.getenv('INSTA_PASSWORD')
    
    if not TELEGRAM_TOKEN:
        logger.error("❌ توکن تلگرام تنظیم نشده است! لطفا متغیر محیطی TELEGRAM_TOKEN را تنظیم کنید.")
        return
    
    # ایجاد دانلودر اینستاگرام
    insta_downloader = InstagramDownloader()
    
    # اگر اطلاعات ورود اینستاگرام وجود دارد، لاگین کن
    if INSTA_USERNAME and INSTA_PASSWORD:
        logger.info("در حال تلاش برای ورود به اینستاگرام...")
        if not insta_downloader.login(INSTA_USERNAME, INSTA_PASSWORD):
            logger.warning("⚠️ نمی‌توان با اطلاعات ورود ارائه شده وارد شد. ادامه بدون لاگین...")
    else:
        logger.info("اطلاعات ورود اینستاگرام تنظیم نشده. ادامه بدون لاگین...")
    
    # ایجاد و شروع بات تلگرام
    logger.info("🚀 در حال راه اندازی ربات تلگرام...")
    telegram_bot = TelegramBot(TELEGRAM_TOKEN, insta_downloader)
    telegram_bot.start_bot()

if __name__ == '__main__':
    main()
