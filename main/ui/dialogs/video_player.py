# ui/dialogs/video_player.py

"""
Simplified Video Player Dialog using VLC.
Plays video files from a specified directory.
Camera streaming functionality has been removed based on user request.
"""

# Removed QImage as it was only used for camera frames
from PyQt5 import QtWidgets, uic, QtGui, QtCore
from PyQt5.QtCore import Qt, QTimer
import vlc
import sys
import os
import logging
from config.constants import UI_PATHS


class VideoPlayer(QtWidgets.QDialog):
    """Video player dialog supporting video file playback using VLC."""

    def __init__(self, parent=None):
        super(VideoPlayer, self).__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing Simplified VideoPlayer Dialog (VLC Only)")

        # Use UI_PATHS["VIDEOS"] instead of self-config
        self.config = {
            "video_dir": os.path.dirname(UI_PATHS["VIDEOS"]),
            "video_list": [],
            "vlc_options": ["--no-xlib", "--quiet", "--no-audio"], # Default VLC options
        }

        # Resource tracking
        self.resources = {
            "vlc_instance": None,
            "media_player": None,
            "timers": {
                "update": QTimer(self),  # UI updates timer remains
            },
        }

        # State tracking
        self.video_state = {
            "current_video_index": 0,
            "video_path": "",
            "is_playing": False,
        }


        try:
            video_directory = self.config["video_dir"]
            if os.path.exists(video_directory):
                # Find all .mp4 files and sort them
                self.config["video_list"] = sorted([
                    f
                    for f in os.listdir(video_directory)
                    if f.lower().endswith(".mp4") and os.path.isfile(os.path.join(video_directory, f))
                ])
                if not self.config["video_list"]:
                    self.logger.warning(f"No .mp4 files found in {video_directory}")
                else:
                     self.logger.info(f"Found videos: {self.config['video_list']}")
            else:
                self.logger.error(f"Video directory not found: {video_directory}")
                self.config["video_list"] = ["1.mp4"] # Fallback if dir missing?

        except Exception as e:
            # Log error during scanning, list remains empty or fallback
            self.logger.error(f"Error scanning video directory '{video_directory}': {e}")
            # self.config["video_list"] = ["1.mp4"] # Fallback on error?

        # Setup UI, Timers, Signals, and VLC
        self._setup_ui()
        self._setup_timers() # Only sets up the 'update' timer now
        self._connect_signals()
        self._init_vlc() # Initialize VLC early

    def _setup_ui(self):
        """Initialize the UI elements."""
        self.logger.debug("Setting up UI")
        try:
            # Load the UI file
            # Use absolute path relative to the main directory
            import os
            ui_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ui", "guis", "video-player.ui")
            uic.loadUi(ui_file_path, self)

            # Get UI elements (ensure names match your .ui file)
            self.video_container = self.findChild(QtWidgets.QWidget, "video_container")
            self.play_button = self.findChild(QtWidgets.QPushButton, "play_button")
            self.pause_button = self.findChild(QtWidgets.QPushButton, "pause_button")
            self.forward_button = self.findChild(QtWidgets.QLabel, "forward_button_video")
            self.backward_button = self.findChild(QtWidgets.QLabel, "backward_button_video")

            # Check if elements were found
            if not all([self.video_container, self.play_button, self.pause_button, self.forward_button, self.backward_button]):
                self.logger.error("One or more UI elements not found in video-player.ui. Check names.")
                raise RuntimeError("Failed to find required UI elements in video player UI file.")

            # Configure video container layout
            layout = QtWidgets.QVBoxLayout(self.video_container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignCenter)

            # Create and configure video widget (QFrame for VLC)
            self.video_widget = QtWidgets.QFrame(self.video_container)
            self.video_widget.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
            )
            self.video_widget.setStyleSheet("background-color: black; border: none;")
            layout.addWidget(self.video_widget)

            # Removed self.usb_stream_label setup and hiding

            self.logger.debug("UI setup completed")

        except FileNotFoundError:
             self.logger.error(f"Video player UI file '{ui_file_path}' not found.")
             QtWidgets.QMessageBox.critical(self, "UI Error", "Video player UI file not found.")
             QtCore.QTimer.singleShot(0, self.close) # Close dialog if UI missing
        except Exception as e:
            self.logger.exception(f"Failed to setup UI: {e}")
            # Raise the error again or handle it by closing the dialog
            QtWidgets.QMessageBox.critical(self, "UI Error", f"Failed to load video player UI.\nError: {e}")
            QtCore.QTimer.singleShot(0, self.close)

    def _setup_timers(self):
        """Initialize timers for UI updates."""
        self.logger.debug("Setting up UI update timer")
        # Only connect the UI update timer
        self.resources["timers"]["update"].timeout.connect(self.update_ui)
        self.resources["timers"]["update"].start(250) # Update UI state periodically

        # Removed frame timer setup

    def _connect_signals(self):
        """Connect UI signals to their slots."""
        self.logger.debug("Connecting signals")
        if self.play_button:
            self.play_button.clicked.connect(self.play_video)
        if self.pause_button:
            self.pause_button.clicked.connect(self.pause_video)
        if self.forward_button:
            self.forward_button.mousePressEvent = self.show_next_video
        if self.backward_button:
            self.backward_button.mousePressEvent = self.show_previous_video

    def _init_vlc(self):
        """Initialize VLC instance and media player."""
        if self.resources.get("media_player"): return # Already initialized
        self.logger.info("Initializing VLC")
        try:
            # Check if vlc module was imported successfully
            if vlc is None:
                raise ImportError("VLC library not loaded.")

            # Create VLC instance
            self.resources["vlc_instance"] = vlc.Instance(self.config["vlc_options"])
            if not self.resources["vlc_instance"]:
                 raise RuntimeError("Failed to create VLC instance.")

            # Create VLC media player
            self.resources["media_player"] = self.resources["vlc_instance"].media_player_new()
            if not self.resources["media_player"]:
                 raise RuntimeError("Failed to create VLC media player.")

            # Embed the player into the video_widget QFrame
            if sys.platform.startswith("linux"):
                self.resources["media_player"].set_xwindow(self.video_widget.winId())
            elif sys.platform == "win32":
                self.resources["media_player"].set_hwnd(self.video_widget.winId())
            elif sys.platform == "darwin":
                self.resources["media_player"].set_nsobject(int(self.video_widget.winId()))
            else:
                 self.logger.warning(f"Unsupported platform '{sys.platform}' for VLC window embedding.")

            self.logger.debug("VLC initialized successfully")

        except Exception as e:
            self.logger.exception(f"Failed to initialize VLC: {e}")
            QtWidgets.QMessageBox.critical(
                self,
                "VLC Error",
                "Failed to initialize video player.\nPlease ensure VLC is installed and the python-vlc library is compatible.",
            )
            # Disable controls if VLC fails
            if self.play_button: self.play_button.setEnabled(False)
            if self.pause_button: self.pause_button.setEnabled(False)
            # Optionally close the dialog: QtCore.QTimer.singleShot(0, self.close)

    # Removed update_frame method

    def update_ui(self):
        """Update UI elements based on VLC player state."""
        # Simplified: Only update based on VLC player state
        if self.resources.get("media_player"):
            try:
                is_playing_vlc = self.resources["media_player"].is_playing()
                if self.video_state["is_playing"] != is_playing_vlc:
                     self.video_state["is_playing"] = is_playing_vlc
                     self.logger.debug(f"Player state updated: is_playing={self.is_playing}")

                # Update button states
                if self.play_button:
                    # Enable play only if stopped and videos exist in the list
                    self.play_button.setEnabled(not self.video_state["is_playing"] and bool(self.config["video_list"]))
                if self.pause_button:
                    self.pause_button.setEnabled(self.video_state["is_playing"])

            except Exception as e:
                 self.logger.error(f"Error updating UI from VLC state: {e}")
        else:
             # Ensure buttons are disabled if player isn't ready
             if self.play_button: self.play_button.setEnabled(False)
             if self.pause_button: self.pause_button.setEnabled(False)


    # Removed switch_to_camera method

    def load_current_video(self):
        """Load and prepare current video for playback."""
        self.logger.info(f"Attempting to load video index: {self.video_state['current_video_index']}")
        video_list = self.config["video_list"]

        # Check if player and video list are ready
        if not self.resources.get("media_player"):
             self.logger.error("VLC media player not initialized. Cannot load video.")
             return
        if not video_list:
            self.logger.warning("No videos available in the list to play.")
            # Optionally inform user
            # QtWidgets.QMessageBox.warning(self, "No Videos", "No video files found.")
            return

        # Validate index
        if not (0 <= self.video_state["current_video_index"] < len(video_list)):
            self.logger.warning(f"Video index {self.video_state['current_video_index']} out of bounds. Resetting to 0.")
            self.video_state["current_video_index"] = 0
            if not video_list: return # Still no videos?

        try:
            # Get filename and construct full path
            video_filename = video_list[self.video_state["current_video_index"]]
            video_path_str = os.path.join(self.config["video_dir"], video_filename)
            self.video_state["video_path"] = video_path_str # Store the path string
            self.logger.info(f"Loading video: {video_path_str}")


            # Check if file exists
            if not os.path.exists(video_path_str):
                self.logger.error(f"Video file not found: {video_path_str}")
                # Removed the switch_to_camera fallback
                QtWidgets.QMessageBox.warning(self, "File Not Found", f"Video file not found:\n{video_filename}")
                # Maybe try next video or disable playback?
                return

            # Create VLC media object
            media = self.resources["vlc_instance"].media_new(video_path_str)
            if not media:
                 raise RuntimeError("Failed to create VLC media object.")

            # Set media for the player
            self.resources["media_player"].set_media(media)
            media.release() # Release our reference

            self.logger.info(f"Video '{video_filename}' loaded.")

            # Ensure the correct widget is visible (video_widget)
            # Removed usb_stream_label.hide()
            self.video_widget.show()

            # Automatically play the loaded video
            self.play_video()

        except Exception as e:
            self.logger.exception(f"Failed to load video '{self.video_state['video_path']}': {e}")
            # Removed the switch_to_camera fallback
            QtWidgets.QMessageBox.critical(
                self, "Load Error", f"Failed to load video:\n{video_filename}\n\nError: {e}"
            )

    def safe_cleanup(self):
        """Clean up VLC resources."""
        self.logger.info("Cleaning up VideoPlayer resources")

        # Stop timers
        if "update" in self.resources["timers"] and self.resources["timers"]["update"].isActive():
            self.resources["timers"]["update"].stop()
            self.logger.debug("Update timer stopped.")
        # Removed frame timer stop

        # Removed camera resource cleanup

        # Release VLC player
        if self.resources.get("media_player"):
            try:
                player = self.resources["media_player"]
                if player.is_playing():
                    player.stop()
                current_media = player.get_media()
                if current_media:
                    current_media.release()
                player.release()
                self.resources["media_player"] = None
                self.logger.debug("VLC media player released.")
            except Exception as e:
                self.logger.error(f"Error releasing VLC media player: {e}")

        # Release VLC instance
        if self.resources.get("vlc_instance"):
            try:
                self.resources["vlc_instance"].release()
                self.resources["vlc_instance"] = None
                self.logger.debug("VLC instance released.")
            except Exception as e:
                self.logger.error(f"Error releasing VLC instance: {e}")

        self.logger.info("VideoPlayer cleanup finished.")

    # --- Event Handlers ---

    def showEvent(self, event):
        """Handle dialog show event."""
        self.logger.debug("VideoPlayer showEvent triggered")
        try:
            # Ensure VLC is initialized
            if not self.resources.get("media_player"):
                self._init_vlc()
            # Load the current video if VLC is ready
            if self.resources.get("media_player"):
                self.load_current_video()
            super().showEvent(event)
        except Exception as e:
            self.logger.exception(f"Error during showEvent: {e}")
            super().showEvent(event) # Still call parent

    def closeEvent(self, event):
        """Handle dialog close event."""
        self.logger.debug("VideoPlayer closeEvent triggered")
        self.safe_cleanup() # Ensure cleanup on close
        super().closeEvent(event)

    def hideEvent(self, event):
        """Handle dialog hide event."""
        self.logger.debug("VideoPlayer hideEvent triggered")
        try:
            # Stop playback when hidden
            if self.resources.get("media_player") and self.resources["media_player"].is_playing():
                self.resources["media_player"].stop()
                self.video_state["is_playing"] = False
                self.logger.info("Video playback stopped on hide.")
                self.update_ui() # Update button states

            # Removed camera cleanup on hide

            super().hideEvent(event)
        except Exception as e:
            self.logger.exception(f"Error during hideEvent: {e}")
            super().hideEvent(event)

    # --- Control Slots ---

    def play_video(self):
        """Start video playback."""
        # Removed check for showing_stream
        player = self.resources.get("media_player")
        if player and not player.is_playing():
            # Ensure media is loaded
            if not player.get_media():
                self.logger.warning("Play called but no media loaded. Loading current video.")
                self.load_current_video()
                # Check again, return if still no media
                if not player.get_media():
                     self.logger.error("Failed to load media, cannot play.")
                     return

            self.logger.info(f"Playing video: {self.video_state['video_path']}")
            try:
                result = player.play()
                if result == -1:
                     self.logger.error("VLC play() returned error.")
                     QtWidgets.QMessageBox.critical(self, "Playback Error", "VLC could not play the video.")
                else:
                     self.video_state["is_playing"] = True
                     self.update_ui()
            except Exception as e:
                 self.logger.exception(f"Error trying to play video: {e}")
                 QtWidgets.QMessageBox.critical(self, "Playback Error", f"Could not play video.\nError: {e}")

        elif not player:
             self.logger.error("Play called but VLC player not initialized.")
        elif player.is_playing():
             self.logger.debug("Play called but video already playing.")


    def pause_video(self):
        """Pause video playback."""
        # Removed check for showing_stream
        player = self.resources.get("media_player")
        if player and player.is_playing():
            self.logger.info(f"Pausing video: {self.video_state['video_path']}")
            try:
                player.pause() # pause() toggles in VLC
                self.video_state["is_playing"] = False # Assume pause worked
                self.update_ui()
            except Exception as e:
                 self.logger.exception(f"Error trying to pause video: {e}")
        elif not player:
             self.logger.error("Pause called but VLC player not initialized.")
        elif not player.get_media() or not player.can_pause():
             self.logger.debug("Pause called but video not playing or cannot be paused.")


    def show_next_video(self, event):
        """Switch to the next video in the list."""
        video_list = self.config["video_list"]
        if not video_list: return # No videos
        self.logger.debug("Next video requested")

        # Stop current playback
        player = self.resources.get("media_player")
        if player and player.get_media():
            if player.is_playing():
                player.stop()
        self.video_state["is_playing"] = False

        # Cycle index
        self.video_state["current_video_index"] += 1
        if self.video_state["current_video_index"] >= len(video_list):
            self.video_state["current_video_index"] = 0 # Wrap around

        # Removed switch_to_camera logic
        self.load_current_video()

    def show_previous_video(self, event):
        """Switch to the previous video in the list."""
        video_list = self.config["video_list"]
        if not video_list: return # No videos
        self.logger.debug("Previous video requested")

        # Stop current playback
        player = self.resources.get("media_player")
        if player and player.get_media():
             if player.is_playing():
                player.stop()
        self.video_state["is_playing"] = False

        # Removed check for showing_stream

        # Cycle index
        self.video_state["current_video_index"] -= 1
        if self.video_state["current_video_index"] < 0:
            self.video_state["current_video_index"] = len(video_list) - 1 # Wrap around

        self.load_current_video()

