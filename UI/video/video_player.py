from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl, Qt


class VideoPlayer(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        uic.loadUi("video-player.ui", self)

        # Setup video widget
        self.videoWidget = self.findChild(QVideoWidget, "videoWidget")

        # Setup media player
        self.mediaPlayer = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.mediaPlayer.setVideoOutput(self.videoWidget)

        # Load video file
        video_path = "path/to/your/video.mp4"
        self.mediaPlayer.setMedia(QMediaContent(QUrl.fromLocalFile(video_path)))

        # Connect buttons and slider
        self.play_button.clicked.connect(self.play_video)
        self.pause_button.clicked.connect(self.pause_video)
        self.seekSlider.sliderMoved.connect(self.set_position)

        # Connect media player signals
        self.mediaPlayer.positionChanged.connect(self.position_changed)
        self.mediaPlayer.durationChanged.connect(self.duration_changed)

    def play_video(self):
        self.mediaPlayer.play()

    def pause_video(self):
        self.mediaPlayer.pause()

    def set_position(self, position):
        self.mediaPlayer.setPosition(position)

    def position_changed(self, position):
        self.seekSlider.setValue(position)

    def duration_changed(self, duration):
        self.seekSlider.setRange(0, duration)


if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    window = MP4Player()
    window.show()
    app.exec_()
