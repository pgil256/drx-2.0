from PyQt5 import QtWidgets, uic, QtGui, QtCore
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage
import cv2
import vlc
import sys
import os
import logging


class VideoPlayer(QtWidgets.QDialog):
    """Video player dialog supporting both video files and USB camera streaming."""

    def __init__(self, parent=None):
        super(VideoPlayer, self).__init__(parent)
        self.logger = logging.getLogger(__name__)

        # Configuration
        base_dir = "/home/pi/drx-2.0/main"
        self.config = {
            "video_dir": os.path.join(base_dir, "ui", "media", "videos"),
            "video_list": [],
            "camera_indices": list(range(3)),
            "frame_rate": 30,
            "vlc_options": ["--no-xlib", "--quiet", "--no-audio"],
        }

        # Resource tracking
        self.resources = {
            "vlc_instance": None,
            "media_player": None,
            "camera": None,
            "timers": {
                "update": QTimer(self),  # UI updates
                "frame": QTimer(self),  # Camera frames
            },
        }

        # State tracking
        self.video_state = {
            "showing_stream": False,
            "current_video_index": 0,
            "video_path": "",
            "is_playing": False,
        }

        # Populate video list
        try:
            if os.path.exists(self.config["video_dir"]):
                self.config["video_list"] = [
                    f
                    for f in os.listdir(self.config["video_dir"])
                    if f.endswith(".mp4")
                ]
                if not self.config["video_list"]:
                    self.logger.warning(
                        f"No .mp4 files found in {self.config['video_dir']}"
                    )
                    self.config["video_list"] = ["1.mp4"]
            else:
                print(
                    f"Video directory not found: {self.config['video_dir']}"
                )
                self.config["video_list"] = ["1.mp4"]
        except Exception as e:
            print(f"Error scanning video directory: {e}")
            self.config["video_list"] = ["1.mp4"]

        self._setup_ui()
        self._setup_timers()
        self._connect_signals()

    def _setup_ui(self):
        """Initialize the UI elements."""
        try:
            uic.loadUi("ui/guis/video-player.ui", self)

            # Get UI elements
            self.video_container = self.findChild(QtWidgets.QWidget, "video_container")
            self.play_button = self.findChild(QtWidgets.QPushButton, "play_button")
            self.pause_button = self.findChild(QtWidgets.QPushButton, "pause_button")
            self.forward_button = self.findChild(
                QtWidgets.QLabel, "forward_button_video"
            )
            self.backward_button = self.findChild(
                QtWidgets.QLabel, "backward_button_video"
            )

            # Configure video container layout
            layout = QtWidgets.QVBoxLayout(self.video_container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignCenter)

            # Create and configure video widget
            self.video_widget = QtWidgets.QFrame(self.video_container)
            self.video_widget.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
            )
            self.video_widget.setStyleSheet(
                """
                background-color: black;
                border: none;
            """
            )
            layout.addWidget(self.video_widget)

            # Create and configure USB stream label
            self.usb_stream_label = QtWidgets.QLabel(self)
            self.usb_stream_label.setAlignment(Qt.AlignCenter)
            self.usb_stream_label.setMinimumSize(400, 200)
            self.usb_stream_label.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
            )
            self.usb_stream_label.setStyleSheet(
                """
                background-color: black;
                border: none;
            """
            )
            layout.addWidget(self.usb_stream_label)
            self.usb_stream_label.hide()

            self.logger.debug("UI setup completed")

        except FileNotFoundError as e:
            from utils.exceptions import UIException
            error = UIException(f"UI file not found: {e}", ui_file="ui/guis/video-player.ui")
            print(f"Failed to setup UI: {error}")
            raise error
        except Exception as e:
            from utils.exceptions import WidgetError
            error = WidgetError(f"Failed to initialize video player UI: {e}")
            print(f"Failed to setup UI: {error}")
            raise error

    def _setup_timers(self):
        """Initialize timers for UI updates and video frames."""
        self.resources["timers"]["update"].timeout.connect(self.update_ui)
        self.resources["timers"]["update"].start(100)

        self.resources["timers"]["frame"].timeout.connect(self.update_frame)

    def _connect_signals(self):
        """Connect UI signals to their slots."""
        self.play_button.clicked.connect(self.play_video)
        self.pause_button.clicked.connect(self.pause_video)
        self.forward_button.mousePressEvent = self.show_next_video
        self.backward_button.mousePressEvent = self.show_previous_video

    def _init_vlc(self):
        """Initialize VLC instance and media player."""
        try:
            if not self.resources["vlc_instance"]:
                self.resources["vlc_instance"] = vlc.Instance(
                    self.config["vlc_options"]
                )

            if not self.resources["media_player"]:
                self.resources["media_player"] = self.resources[
                    "vlc_instance"
                ].media_player_new()

                if sys.platform.startswith("linux"):
                    self.resources["media_player"].set_xwindow(
                        self.video_widget.winId()
                    )
                elif sys.platform == "win32":
                    self.resources["media_player"].set_hwnd(self.video_widget.winId())
                elif sys.platform == "darwin":
                    self.resources["media_player"].set_nsobject(
                        int(self.video_widget.winId())
                    )

            self.logger.debug("VLC initialized successfully")

        except AttributeError as e:
            from utils.exceptions import WidgetError
            error = WidgetError(f"VLC configuration error: {e}")
            print(f"Failed to initialize VLC: {error}")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to initialize video player: {error}"
            )
            self.close()
        except Exception as e:
            from utils.exceptions import UIException
            error = UIException(f"Failed to initialize VLC: {e}")
            print(f"Failed to initialize VLC: {error}")
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                "Failed to initialize video player. Please check VLC installation.",
            )
            self.close()

    def update_frame(self):
        """Update camera frame display."""
        if not self.video_state["showing_stream"] or not self.resources["camera"]:
            return

        try:
            ret, frame = self.resources["camera"].read()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame.shape
                qt_image = QImage(frame.data, w, h, ch * w, QImage.Format_RGB888)

                # Scale and center the image
                label_size = self.usb_stream_label.size()
                scaled_pixmap = QPixmap.fromImage(qt_image).scaled(
                    label_size.width(),
                    label_size.height(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )

                # Create centered pixmap
                x_offset = (label_size.width() - scaled_pixmap.width()) // 2
                y_offset = (label_size.height() - scaled_pixmap.height()) // 2

                final_pixmap = QPixmap(label_size)
                final_pixmap.fill(Qt.black)

                painter = QtGui.QPainter(final_pixmap)
                painter.drawPixmap(x_offset, y_offset, scaled_pixmap)
                painter.end()

                self.usb_stream_label.setPixmap(final_pixmap)

        except Exception as e:
            print(f"Frame update failed: {e}")
            self.resources["timers"]["frame"].stop()

    def update_ui(self):
        """Update UI elements."""
        if not self.video_state["showing_stream"] and self.resources["media_player"]:
            self.play_button.setEnabled(not self.video_state["is_playing"])
            self.pause_button.setEnabled(self.video_state["is_playing"])

    def switch_to_camera(self):
        """Switch display to USB camera feed."""
        try:
            if self.resources["media_player"]:
                self.resources["media_player"].stop()

            if self.resources["camera"]:
                self.resources["camera"].release()

            for idx in self.config["camera_indices"]:
                try:
                    self.resources["camera"] = cv2.VideoCapture(idx)
                    if self.resources["camera"].isOpened():
                        print(f"Connected to camera at index {idx}")
                        break
                except Exception as e:
                    self.logger.warning(f"Failed to open camera at index {idx}: {e}")

            if not self.resources["camera"] or not self.resources["camera"].isOpened():
                raise RuntimeError("No available camera found")

            self.video_state["showing_stream"] = True
            self.video_widget.hide()
            self.usb_stream_label.show()

            self.resources["timers"]["frame"].start(1000 // self.config["frame_rate"])
            return True

        except Exception as e:
            print(f"Failed to switch to camera: {e}")
            return False

    def load_current_video(self):
        """Load and prepare current video for playback."""
        try:
            if not self.config["video_list"]:
                raise RuntimeError("No videos available to play")

            if self.video_state["current_video_index"] >= len(
                self.config["video_list"]
            ):
                self.video_state["current_video_index"] = 0

            self._init_vlc()

            video_path = os.path.join(
                self.config["video_dir"],
                self.config["video_list"][self.video_state["current_video_index"]],
            )

            if not os.path.exists(video_path):
                print(f"Video file not found: {video_path}")
                if self.switch_to_camera():
                    return
                raise FileNotFoundError(f"Video file not found: {video_path}")

            media = self.resources["vlc_instance"].media_new(video_path)
            self.resources["media_player"].set_media(media)
            self.video_state["video_path"] = video_path

            self.video_state["showing_stream"] = False
            self.usb_stream_label.hide()
            self.video_widget.show()

            self.play_video()

        except Exception as e:
            print(f"Failed to load video: {e}")
            if not self.video_state["showing_stream"] and self.switch_to_camera():
                print("Switched to camera stream after video load failed")
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Error",
                    f"Failed to load video and camera not available: {str(e)}",
                )

    def safe_cleanup(self):
        """Clean up all resources."""
        self.logger.debug("Starting cleanup")

        for timer in self.resources["timers"].values():
            if timer and timer.isActive():
                timer.stop()

        if self.resources["camera"]:
            self.resources["camera"].release()
            self.resources["camera"] = None

        if self.resources["media_player"]:
            self.resources["media_player"].stop()
            if self.resources["media_player"].get_media():
                self.resources["media_player"].get_media().release()
            self.resources["media_player"].release()
            self.resources["media_player"] = None

        if self.resources["vlc_instance"]:
            self.resources["vlc_instance"].release()
            self.resources["vlc_instance"] = None

        self.logger.debug("Cleanup completed")

    def showEvent(self, event):
        """Handle dialog show event."""
        self.logger.debug("Showing VideoPlayer")
        try:
            self._init_vlc()
            self.load_current_video()
            super().showEvent(event)
        except Exception as e:
            print(f"Error during show: {e}")
            super().showEvent(event)

    def closeEvent(self, event):
        """Handle dialog close event."""
        self.logger.debug("Closing VideoPlayer")
        try:
            self.safe_cleanup()
            super().closeEvent(event)
        except Exception as e:
            print(f"Error during close: {e}")
            super().closeEvent(event)

    def hideEvent(self, event):
        """Handle dialog hide event."""
        self.logger.debug("Hiding VideoPlayer")
        try:
            if self.resources["media_player"]:
                self.resources["media_player"].stop()
            if self.resources["camera"]:
                self.resources["camera"].release()
                self.resources["camera"] = None
            super().hideEvent(event)
        except Exception as e:
            print(f"Error during hide: {e}")
            super().hideEvent(event)

    def play_video(self):
        """Start video playback or camera stream."""
        if self.video_state["showing_stream"]:
            self.resources["timers"]["frame"].start(1000 // self.config["frame_rate"])
        elif self.resources["media_player"]:
            self.resources["media_player"].play()
            self.video_state["is_playing"] = True

    def pause_video(self):
        """Pause video playback or camera stream."""
        if self.video_state["showing_stream"]:
            self.resources["timers"]["frame"].stop()
        elif self.resources["media_player"]:
            self.resources["media_player"].pause()
            self.video_state["is_playing"] = False

    def show_next_video(self, event):
        """Switch to next video or camera stream."""
        self.video_state["current_video_index"] += 1
        if self.video_state["current_video_index"] >= len(self.config["video_list"]):
            if self.switch_to_camera():
                print("Switched to camera stream")
            else:
                self.video_state["current_video_index"] = 0
                self.load_current_video()
        else:
            self.load_current_video()

    def show_previous_video(self, event):
        """Switch to previous video."""
        if self.video_state["showing_stream"]:
            self.video_state["showing_stream"] = False
            self.video_state["current_video_index"] = len(self.config["video_list"]) - 1
            self.load_current_video()
        else:
            self.video_state["current_video_index"] = max(
                0, self.video_state["current_video_index"] - 1
            )
            self.load_current_video()
