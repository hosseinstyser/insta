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
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def sanitize_filename(self, filename: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '', filename)

    def login(self, username: str, password: str) -> bool:
        try:
            self.loader.context.login(username, password)
            self.loader.save_session_to_file()
            logger.info("Login successful")
            return True
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            return False

    def download_media(self, url: str, filename: str = None) -> Optional[str]:
        try:
            response = self.session.get(url, stream=True, timeout=60)
            response.raise_for_status()

            filename = filename or os.path.basename(urlparse(url).path)
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

            return save_path
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return None

    def get_shortcode(self, url: str) -> str:
        pattern = r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv)/([^/?#&]+)'
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        raise ValueError("Invalid Instagram URL")

    def get_post_info(self, url: str) -> Tuple[List[Tuple[str, str, str]], str]:
        try:
            shortcode = self.get_shortcode(url)
            post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
            
            media_list = []
            caption = post.caption if post.caption else ""
            
            if post.typename == 'GraphSidecar':
                for idx, node in enumerate(post.get_sidecar_nodes(), start=1):
                    if node.is_video:
                        media_list.append((node.video_url, 'video', f"{post.shortcode}_{idx}.mp4"))
                    else:
                        media_list.append((node.display_url, 'photo', f"{post.shortcode}_{idx}.jpg"))
            else:
                if post.is_video:
                    media_list.append((post.video_url, 'video', f"{post.shortcode}.mp4"))
                else:
                    media_list.append((post.url, 'photo', f"{post.shortcode}.jpg"))
            
            return media_list, caption
        except Exception as e:
            logger.error(f"Error getting post info: {e}")
            return [], ""

class TelegramBot:
    def __init__(self, token: str, insta_downloader: InstagramDownloader):
        self.token = token
        self.insta_downloader = insta_downloader
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(CommandHandler("help", self.help))
        self.dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), self.handle_message))

    def start(self, update: Update, context: CallbackContext):
        update.message.reply_text("🤖 Instagram Downloader Bot\n\nSend me an Instagram link!")

    def help(self, update: Update, context: CallbackContext):
        update.message.reply_text("ℹ️ Just send me an Instagram post/reel/IGTV link")

    def is_valid_instagram_url(self, url: str) -> bool:
        patterns = [
            r'https?://(www\.)?instagram\.com/p/',
            r'https?://(www\.)?instagram\.com/reel/',
            r'https?://(www\.)?instagram\.com/tv/'
        ]
        return any(re.search(pattern, url) for pattern in patterns)

    def handle_message(self, update: Update, context: CallbackContext):
        text = update.message.text
        
        if not self.is_valid_instagram_url(text):
            update.message.reply_text("❌ Please send a valid Instagram link")
            return
        
        try:
            update.message.reply_text("⏳ Processing...")
            
            media_list, caption = self.insta_downloader.get_post_info(text)
            
            if not media_list:
                update.message.reply_text("❌ Could not get media from this link")
                return
            
            downloaded_files = []
            for media_url, media_type, filename in media_list:
                file_path = self.insta_downloader.download_media(media_url, filename)
                if file_path:
                    downloaded_files.append((file_path, media_type))
            
            self.send_media(update, downloaded_files, caption)
            
        except Exception as e:
            logger.error(f"Error: {e}")
            update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            if 'downloaded_files' in locals():
                self.cleanup_files(downloaded_files)

    def send_media(self, update: Update, files: List[Tuple[str, str]], caption: str = ""):
        if not files:
            return
            
        if len(files) == 1:
            file_path, media_type = files[0]
            try:
                with open(file_path, 'rb') as f:
                    if media_type == 'photo':
                        update.message.reply_photo(f, caption=caption[:1000])
                    else:
                        update.message.reply_video(f, caption=caption[:1000])
            except Exception as e:
                logger.error(f"Send failed: {e}")
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
                    logger.error(f"Media prep failed: {e}")
            
            if media_group:
                try:
                    update.message.reply_media_group(media=media_group)
                except Exception as e:
                    logger.error(f"Group send failed: {e}")

    def cleanup_files(self, files: List[Tuple[str, str]]):
        for file_path, _ in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"Cleanup failed: {e}")

    def start_bot(self):
        logger.info("Bot started")
        self.updater.start_polling()
        self.updater.idle()

def main():
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '7732534464:AAG-qNiJiAEz5F2-D4Y_6fqqw753bzzFntc')
    INSTA_USERNAME = os.getenv('INSTA_USERNAME')
    INSTA_PASSWORD = os.getenv('INSTA_PASSWORD')
    
    if not TELEGRAM_TOKEN:
        logger.error("Telegram token missing")
        return
    
    downloader = InstagramDownloader()
    if INSTA_USERNAME and INSTA_PASSWORD:
        if not downloader.login(INSTA_USERNAME, INSTA_PASSWORD):
            logger.warning("Instagram login failed - continuing with public access")
    
    bot = TelegramBot(TELEGRAM_TOKEN, downloader)
    bot.start_bot()

if __name__ == '__main__':
    main()
