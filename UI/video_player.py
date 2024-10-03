import os
from PyQt5 import uic, QtWidgets
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget


class VideoPlayer(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(VideoPlayer, self).__init__(parent)
        uic.loadUi("video-player.ui", self)

        # Create QVideoWidget and add it to the video_container
        self.video_player_widget = QVideoWidget()
        video_container = self.findChild(QtWidgets.QWidget, "video_container")
        layout = QtWidgets.QVBoxLayout(video_container)
        layout.addWidget(self.video_player_widget)
        video_container.setLayout(layout)

        self.play_button = self.findChild(QtWidgets.QPushButton, "play_button")
        self.pause_button = self.findChild(QtWidgets.QPushButton, "pause_button")
        self.seekSlider = self.findChild(QtWidgets.QSlider, "seekSlider")

        self.forward_button_video = self.findChild(
            QtWidgets.QLabel, "forward_button_video"
        )
        self.backward_button_video = self.findChild(
            QtWidgets.QLabel, "backward_button_video"
        )

        self.mediaPlayer = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.mediaPlayer.setVideoOutput(self.video_player_widget)

        self.play_button.clicked.connect(self.play_video)
        self.pause_button.clicked.connect(self.pause_video)
        self.seekSlider.sliderMoved.connect(self.set_position)

        self.mediaPlayer.positionChanged.connect(self.position_changed)
        self.mediaPlayer.durationChanged.connect(self.duration_changed)

        self.mediaPlayer.error.connect(self.handle_error)

        # Connect video navigation buttons
        self.forward_button_video.mousePressEvent = self.show_next_video
        self.backward_button_video.mousePressEvent = self.show_previous_video

        # Initialize video list and current video index
        self.video_list = ["1.mp4", "2.mp4"]
        self.current_video_index = 0

    def play_video(self):
        if self.mediaPlayer.state() != QMediaPlayer.PlayingState:
            self.mediaPlayer.play()

    def pause_video(self):
        if self.mediaPlayer.state() == QMediaPlayer.PlayingState:
            self.mediaPlayer.pause()

    def set_position(self, position):
        self.mediaPlayer.setPosition(position)

    def position_changed(self, position):
        self.seekSlider.setValue(position)

    def duration_changed(self, duration):
        self.seekSlider.setRange(0, duration)

    def set_media(self, file_path):
        if os.path.exists(file_path):
            if os.access(file_path, os.R_OK):
                self.mediaPlayer.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
            else:
                QtWidgets.QMessageBox.critical(
                    self, "Error", f"Permission denied: Cannot read {file_path}"
                )
        else:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"Video file not found: {file_path}"
            )

    def handle_error(self):
        error_msg = self.mediaPlayer.errorString()
        QtWidgets.QMessageBox.critical(self, "Media Error", f"Error: {error_msg}")

    def show_next_video(self, event):
        self.current_video_index = (self.current_video_index + 1) % len(self.video_list)
        self.load_current_video()

    def show_previous_video(self, event):
        self.current_video_index = (self.current_video_index - 1) % len(self.video_list)
        self.load_current_video()

    def load_current_video(self):
        video_path = os.path.abspath(
            f"videos/{self.video_list[self.current_video_index]}"
        )
        self.set_media(video_path)
        self.play_video()
