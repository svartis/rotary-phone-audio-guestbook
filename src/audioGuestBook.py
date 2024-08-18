#! /usr/bin/env python3

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from signal import pause

import yaml
from gpiozero import Button

from audioInterface import AudioInterface

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AudioGuestBook:
    """
    Manages the rotary phone audio guest book application.

    This class initializes the application, handles phone hook events, and
    coordinates audio playback and recording based on the phone's hook status.

    Attributes:
        config_path (str): Path to the application configuration file.
        config (dict): Configuration parameters loaded from the YAML file.
        audio_interface (AudioInterface): Interface for audio playback and recording.
    """

    def __init__(self, config_path):
        """
        Initializes the audio guest book application with specified configuration.

        Args:
            config_path (str): Path to the configuration YAML file.
        """
        self.config_path = config_path
        self.config = self.load_config()
        self.audio_interface = AudioInterface(
            alsa_hw_mapping=self.config["alsa_hw_mapping"],
            format=self.config["format"],
            file_type=self.config["file_type"],
            recording_limit=self.config["recording_limit"],
            sample_rate=self.config["sample_rate"],
            channels=self.config["channels"],
            mixer_control_name=self.config["mixer_control_name"],
        )
        self.setup_hook()
        self.setup_record_greeting()
        self.continue_playback = False

    def load_config(self):
        """
        Loads the application configuration from a YAML file.

        Raises:
            FileNotFoundError: If the configuration file does not exist.
        """
        try:
            with open(self.config_path, "r") as f:
                return yaml.safe_load(f)
        except FileNotFoundError as e:
            logger.error(f"Configuration file not found: {e}")
            sys.exit(1)

    def setup_hook(self):
        """
        Sets up the phone hook switch with GPIO based on the configuration.
        """
        hook_gpio = self.config["hook_gpio"]
        pull_up = self.config["hook_type"] == "NC"
        bounce_time = self.config["hook_bounce_time"]
        self.hook = Button(hook_gpio, pull_up=pull_up, bounce_time=bounce_time)
        self.hook.when_pressed = self.off_hook
        self.hook.when_released = self.on_hook

    def off_hook(self):
        """
        Handles the off-hook event to start playback and recording.
        """
        logger.info("Phone off hook, ready to begin!")

        self.continue_playback = True  # Ensure playback can continue
        # Start the greeting playback in a separate thread
        self.greeting_thread = threading.Thread(target=self.play_greeting_and_beep)
        self.greeting_thread.start()

    def start_recording(self, output_file: str):
        """
        Starts the audio recording process and sets a timer for time exceeded event.
        """
        self.audio_interface.start_recording(output_file)
        logger.info("Recording started...")

        # Start a timer to handle the time exceeded event
        self.timer = threading.Timer(
            self.config["time_exceeded_length"], self.time_exceeded
        )
        self.timer.start()

    def play_greeting_and_beep(self):
        """
        Plays the greeting and beep sounds, checking for the on-hook event.
        """
        # Play the greeting
        self.audio_interface.continue_playback = self.continue_playback
        logger.info("Playing voicemail...")
        self.audio_interface.play_audio(
            self.config["greeting"],
            self.config["greeting_volume"],
            self.config["greeting_start_delay"],
        )

        # Check if the phone is still off-hook
        # Start recording already BEFORE the beep
        if self.continue_playback:
            path = str(
                Path(self.config["recordings_path"]) / f"{datetime.now().isoformat()}.wav"
            )
            self.start_recording(path)

        # Play the beep
        if self.continue_playback:
            logger.info("Playing beep...")
            self.audio_interface.play_audio(
                self.config["beep"],
                self.config["beep_volume"],
                self.config["beep_start_delay"],
            )

    def on_hook(self):
        """
        Handles the on-hook event to stop and save the recording.
        """
        logger.info("Phone on hook. Ending call and saving recording.")
        self.stop_recording_and_playback()

    def time_exceeded(self):
        """
        Handles the event when the recording time exceeds the limit.
        """
        logger.info("Recording time exceeded. Stopping recording.")
        self.audio_interface.stop_recording()
        self.audio_interface.play_audio(
            self.config["time_exceeded"], self.config["time_exceeded_volume"], 0
        )

    def setup_record_greeting(self):
        """
        Sets up the phone record greeting switch with GPIO based on the configuration.
        """
        record_greeting_gpio = self.config["record_greeting_gpio"]
        if record_greeting_gpio == 0:
            logger.info("record_greeting_gpio is 0, skipping setup.")
            return
        pull_up = self.config["record_greeting_type"] == "NC"
        bounce_time = self.config["record_greeting_bounce_time"]
        self.record_greeting = Button(record_greeting_gpio, pull_up=pull_up, bounce_time=bounce_time)
        self.record_greeting.when_pressed = self.pressed_record_greeting
        self.record_greeting.when_released = self.released_record_greeting

    def pressed_record_greeting(self):
        """
        Handles the record greeting to start recording a new greeting message.
        """
        logger.info("Record greeting pressed, ready to begin!")

        self.continue_playback = True  # Ensure record greeting can continue
        # Start the record greeting in a separate thread
        self.greeting_thread = threading.Thread(target=self.beep_and_record_greeting)
        self.greeting_thread.start()

    def released_record_greeting(self):
        """
        Handles the record greeting event to stop and save the greeting.
        """
        logger.info("Record greeting released. Save the greeting.")
        self.stop_recording_and_playback()

    def beep_and_record_greeting(self):
        """
        Plays the beep and start recording a new greeting message #, checking for the on-hook event.
        """

        self.audio_interface.continue_playback = self.continue_playback

        # Play the beep
        if self.continue_playback:
            logger.info("Playing beep...")
            self.audio_interface.play_audio(
                self.config["beep"],
                self.config["beep_volume"],
                self.config["beep_start_delay"],
            )

        # Check if the record greeting message button is still pressed      
        if self.continue_playback:
            path = str(
                Path(self.config["greeting"])
            )
            # Start recording new greeting message       
            self.start_recording(path)

    def stop_recording_and_playback(self):
        """
        Stop recording and playback processes.
        """
        self.continue_playback = False  # Stop playback
        self.audio_interface.stop_recording()
        if hasattr(self, "timer"):
            self.timer.cancel()
        if hasattr(self, "greeting_thread") and self.greeting_thread.is_alive():
            logger.info("Stopping playback.")
            self.audio_interface.stop_playback()

    def run(self):
        """
        Starts the main event loop waiting for phone hook events.
        """
        logger.info("System ready. Lift the handset to start.")
        pause()


if __name__ == "__main__":
    CONFIG_PATH = Path(__file__).parent / "../config.yaml"
    logger.info(f"Using configuration file: {CONFIG_PATH}")
    guest_book = AudioGuestBook(CONFIG_PATH)
    guest_book.run()
