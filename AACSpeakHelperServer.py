import logging
import os
import sys


def setup_logging():
    if getattr(sys, 'frozen', False):
        # If the application is run as a bundle, use the AppData directory
        log_dir = os.path.join(os.path.expanduser("~"), 'AppData', 'Roaming', 'Ace Centre', 'AACSpeakHelper')
    else:
        # If run from a Python environment, use the current directory
        log_dir = os.path.dirname(os.path.abspath(__file__))

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_file = os.path.join(log_dir, 'app.log')

    logging.basicConfig(
        filename=log_file,
        filemode='a',
        format="%(asctime)s — %(name)s — %(levelname)s — %(funcName)s:%(lineno)d — %(message)s",
        level=logging.DEBUG
    )

    return log_file


logfile = setup_logging()

import asyncio
import json
import sys
import time
import pyperclip
import pyttsx3
import pywintypes
import win32file
import win32pipe
from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QThread, Signal, Slot, QTimer
from deep_translator import *
import utils
from GUI_TranslateAndTTS.language_dictionary import *
import tts_utils
import subprocess
import configparser


class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, icon, parent=None):
        super().__init__(icon, parent)
        self.parent = parent
        menu = QMenu(parent)
        self.config_path, self.audio_files_path = utils.get_paths(None)
        logging.info(f"Config path: {self.config_path}")
        logging.info(f"Audio files path: {self.audio_files_path}")

        openLogsAction = QAction("Open logs", self)
        menu.addAction(openLogsAction)
        openLogsAction.triggered.connect(self.open_logs)

        openCacheAction = QAction("Open Cache", self)
        menu.addAction(openCacheAction)
        openCacheAction.triggered.connect(self.open_cache)

        menu.addSeparator()

        self.lastRunAction = QAction("Last run info not available", self)
        self.lastRunAction.setEnabled(False)
        menu.addAction(self.lastRunAction)

        exitAction = menu.addAction("Exit")
        exitAction.triggered.connect(self.exit)

        self.setContextMenu(menu)

    def exit(self):
        self.parent.pipe_thread.quit()
        QApplication.quit()

    def update_last_run_info(self, last_run_time, duration):
        self.lastRunAction.setText(f"Last run at {last_run_time} - took {duration} secs")

    def open_logs(self):
        logging.info("Opening logs...")
        subprocess.Popen(['notepad', logfile])

    def open_cache(self):
        logging.info("Opening cache...")
        subprocess.Popen(['explorer', self.audio_files_path])
        # Implement cache opening logic here


class PipeServerThread(QThread):
    message_received = Signal(str)
    voices = None

    def run(self):
        pipe_name = r'\\.\pipe\AACSpeakHelper'
        while True:
            pipe = None
            try:
                pipe = win32pipe.CreateNamedPipe(
                    pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES, 65536, 65536,
                    0,
                    None)

                logging.info("Waiting for client connection...")
                win32pipe.ConnectNamedPipe(pipe, None)
                logging.info("Client connected.")

                result, data = win32file.ReadFile(pipe, 64 * 1024)
                if result == 0:
                    message = data.decode()
                    logging.info(f"Received data: {message[:50]}...")
                    self.message_received.emit(message)
                    get_voices = json.loads(message)['args']['listvoices']
                    # Extract data from the received message
                logging.info("Processing complete. Ready for next connection.")
            except Exception as e:
                logging.error(f"Pipe server error: {e}", exc_info=True)
            finally:
                if pipe:
                    while get_voices:
                        if self.voices:
                            win32file.WriteFile(pipe, json.dumps(self.voices).encode())
                            self.voices = None
                            break
                    win32file.CloseHandle(pipe)
                logging.info("Pipe closed. Reopening for next connection.")


class CacheCleanerThread(QThread):
    def run(self):
        remove_stale_temp_files(utils.audio_files_path)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.cache_timer = None
        self.cache_cleaner = None
        self.pipe_thread = None
        self.tray_icon = None
        self.icon = QIcon('assets/translate.ico')
        self.init_ui()
        self.init_pipe_server()
        self.init_cache_cleaner()

    def init_ui(self):
        self.tray_icon = SystemTrayIcon(self.icon, self)
        self.tray_icon.setVisible(True)

    def init_pipe_server(self):
        self.pipe_thread = PipeServerThread()
        self.pipe_thread.message_received.connect(self.handle_message)
        self.pipe_thread.start()

    def init_cache_cleaner(self):
        self.cache_cleaner = CacheCleanerThread()
        self.cache_timer = QTimer(self)
        self.cache_timer.timeout.connect(lambda: self.cache_cleaner.start())
        self.cache_timer.start(24 * 60 * 60 * 1000)  # Run once a day

    @Slot(str)
    def handle_message(self, message):
        try:
            logging.info(f"Handling new message: {message[:50]}...")
            data = json.loads(message)

            # Extract data from the received message
            args = data['args']
            config_dict = data['config']
            clipboard_text = data['clipboard_text']

            # Create a ConfigParser object and update it with received config
            config = configparser.ConfigParser()
            for section, options in config_dict.items():
                config[section] = options

            # Get the config path from the received config
            config_path = config.get('App', 'config_path', fallback=None)
            # Use utils.get_paths to get the paths
            config_path, audio_files_path = utils.get_paths(config_path)

            if 'App' not in config:
                config['App'] = {}
            config['App']['config_path'] = config_path
            config['App']['audio_files_path'] = audio_files_path

            # Initialize utils with the new config and args
            utils.init(config, args)

            # Initialize TTS
            tts_utils.init(utils)
            # if args['listvoices']:
            #     try:
            #         engine = pyttsx3.init(config.get('TTS', 'engine'))
            #         voices = engine.getProperty('voices')
            #         for voice in voices:
            #             print(voice)
            #         self.tray_icon.showMessage('Voice List', '', self.icon, 5000)
            #     except Exception as e:
            #         logging.error(f"List Voice Error: {e}", exc_info=True)
            #         logging.error("List Voice Error!", exc_info=True)
            #         result = utils.ynbox(
            #             str(e) + '\n\nlistvoices method not supported for specified TTS Engine.\n\n Do You want to '
            #                      'open the'
            #                      'Configuration Setup?',
            #             'List Voice Error')
            #         if result:
            #             utils.configure_app()
            #         else:
            #             return

            # Process the clipboard text
            if config.getboolean('translate', 'noTranslate'):
                text_to_process = clipboard_text
            else:
                text_to_process = translate_clipboard(clipboard_text, config)

            # Perform TTS if not bypassed
            if not config.getboolean('TTS', 'bypass_tts', fallback=False):
                tts_utils.speak(text_to_process, args['listvoices'])
            if tts_utils.voices:
                # self.tray_icon.showMessage('Voice List', str(tts_utils.voices), self.icon, 5000)
                self.pipe_thread.voices = tts_utils.voices
            # Replace clipboard if specified
            if config.getboolean('translate', 'replacepb') and text_to_process is not None:
                pyperclip.copy(text_to_process)

            current_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self.tray_icon.update_last_run_info(current_time, "N/A")
            logging.info(f"Processed message at {current_time}")
        except Exception as e:
            logging.error(f"Error handling message: {e}", exc_info=True)
        finally:
            logging.info("Message handling complete.")


def translate_clipboard(text, config):
    try:
        translator = config.get('translate', 'provider')
        key = config.get('translate', f'{translator}_secret_key') if not translator == "GoogleTranslator" else None
        email = config.get('translate', 'email') if translator == 'MyMemoryTranslator' else None
        region = config.get('translate', 'region') if translator == 'MicrosoftTranslator' else None
        pro = config.getboolean('translate', 'deepl_pro') if translator == 'DeeplTranslator' else None
        url = config.get('translate', 'url') if translator == 'LibreProvider' else None
        client_id = config.get('translate', 'papagotranslator_client_id') if translator == 'PapagoTranslator' else None
        appid = config.get('translate', 'baidutranslator_appid') if translator == 'BaiduTranslator' else None

        match translator:
            case "GoogleTranslator":
                translate_instance = GoogleTranslator(source='auto', target=config.get('translate', 'endLang'))
            case "PonsTranslator":
                translate_instance = PonsTranslator(source='auto', target=config.get('translate', 'endLang'))
            case "LingueeTranslator":
                translate_instance = LingueeTranslator(source='auto', target=config.get('translate', 'endLang'))
            case "MyMemoryTranslator":
                translate_instance = MyMemoryTranslator(source=config.get('translate', 'startLang'),
                                                        target=config.get('translate', 'endLang'),
                                                        email=email)
            case "YandexTranslator":
                translate_instance = YandexTranslator(source=config.get('translate', 'startLang'),
                                                      target=config.get('translate', 'endLang'),
                                                      api_key=key)
            case "MicrosoftTranslator":
                translate_instance = MicrosoftTranslator(api_key=key,
                                                         source=config.get('translate', 'startLang'),
                                                         target=config.get('translate', 'endLang'),
                                                         region=region)
            case "QcriTranslator":
                translate_instance = QcriTranslator(source='auto',
                                                    target=config.get('translate', 'endLang'),
                                                    api_key=key)
            case "DeeplTranslator":
                translate_instance = DeeplTranslator(source=config.get('translate', 'startlang'),
                                                     target=config.get('translate', 'endLang'),
                                                     api_key=key,
                                                     use_free_api=not pro)
            case "LibreTranslator":
                translate_instance = LibreTranslator(source=config.get('translate', 'startlang'),
                                                     target=config.get('translate', 'endLang'),
                                                     api_key=key,
                                                     custom_url=url)
            case "PapagoTranslator":
                translate_instance = PapagoTranslator(source='auto',
                                                      target=config.get('translate', 'endLang'),
                                                      client_id=client_id,
                                                      secret_key=key)
            case "ChatGptTranslator":
                translate_instance = ChatGptTranslator(source='auto', target=config.get('translate', 'endLang'))
            case "BaiduTranslator":
                translate_instance = BaiduTranslator(source=config.get('translate', 'startlang'),
                                                     target=config.get('translate', 'endLang'),
                                                     appid=appid,
                                                     appkey=key)
        # elif translator == "DeepLearningTranslator":
        #     translate_instance = BaiduTranslator(source=config.get('translate', 'startlang'),
        #                                          target=config.get('translate', 'endLang'),
        #                                          appid=appid,
        #                                          appkey=key)
        logging.info('Translation Provider is {}'.format(translator))
        logging.info(f'Text [{config.get("translate", "startLang")}]: {text}')

        translation = translate_instance.translate(text)
        logging.info(f'Translation [{config.get("translate", "endLang")}]: {translation}')
        return translation
    except Exception as e:
        logging.error(f"Translation Error: {e}", exc_info=True)


def remove_stale_temp_files(directory_path, ignore_pattern=".db"):
    config = utils.config
    start = time.perf_counter()
    current_time = time.time()
    day = int(config.get('appCache', 'threshold'))
    time_threshold = current_time - day * 24 * 60 * 60
    file_list = []

    for root, dirs, files in os.walk(directory_path):
        for file in files:
            file_path = os.path.join(root, file)
            if ignore_pattern and file.endswith(ignore_pattern) and file.endswith('.db-journal'):
                continue
            try:
                file_modification_time = os.path.getmtime(file_path)
                if file_modification_time < time_threshold:
                    os.remove(file_path)
                    file_list.append(os.path.basename(file_path))
                    logging.info(f"Removed cache file: {file_path}")
            except Exception as e:
                logging.error(f"Error processing file {file_path}: {e}", exc_info=True)

    stop = time.perf_counter() - start
    utils.clear_history(file_list)
    logging.info(f"Cache clearing took {stop:0.5f} seconds.")


# async def main(wav_files_path):
#     logging.info("Starting main function execution...")
#     try:
#         # await asyncio.gather(mainrun(utils.args['listvoices']), remove_stale_temp_files(wav_files_path))
#     except Exception as e:
#         logging.error(f"Error in main function: {e}", exc_info=True)
#     finally:
#         logging.info("Main function execution complete.")


async def mainrun(listvoices: bool):
    config = utils.config
    if listvoices:
        try:
            engine = pyttsx3.init(config.get('TTS', 'engine'))
            voices = engine.getProperty('voices')
            for voice in voices:
                print(voice)
        except Exception as e:
            logging.error(f"List Voice Error: {e}", exc_info=True)
            logging.error("List Voice Error!", exc_info=True)
            result = utils.ynbox(
                str(e) + '\n\nlistvoices method not supported for specified TTS Engine.\n\n Do You want to open the '
                         'Configuration Setup?',
                'List Voice Error')
            if result:
                utils.configure_app()
            else:
                return
    else:
        try:
            start = time.perf_counter()
            if config.getboolean('translate', 'noTranslate'):
                clipboard_text = pyperclip.paste()
                logging.info(f"Text from clipboard: [{clipboard_text}].")
            else:
                clipboard = translate_clipboard()

            stop = time.perf_counter() - start
            logging.info(
                f"{'Clipboard' if config.getboolean('translate', 'noTranslate') else 'Translation'} runtime is {stop:0.5f} seconds.")

            if not config.getboolean('TTS', 'bypass_tts', fallback=False):
                start = time.perf_counter()
                logging.info(f"Text to Speech: {clipboard}")
                tts_utils.speak(clipboard)
                stop = time.perf_counter() - start
                logging.info(f"TTS runtime is {stop:0.5f} seconds.")

            if config.getboolean('translate', 'replacepb') and clipboard is not None:
                pyperclip.copy(clipboard)

        except Exception as e:
            logging.error(f"Runtime Error: {e}", exc_info=True)
            # Handle error (e.g., show dialog)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    sys.exit(app.exec())
