"""
Unit tests for the video player component.
"""
import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from typing import Dict, Any, Optional, List

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Conditionally import PyQt5 to handle environments without GUI
try:
    from PyQt5.QtWidgets import QApplication, QWidget, QDialog
    from PyQt5.QtCore import QUrl
    from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
    from main.ui.dialogs.video_player import VideoPlayer
    PyQt5_AVAILABLE = True
except ImportError:
    PyQt5_AVAILABLE = False
    
from tests.fixtures.ui_mock import (
    UITestFixture, 
    mock_video_player,
    mock_dialog,
    ui_fixture,
    UITestingNotSupportedError
)


@pytest.mark.ui
@pytest.mark.skipif(not PyQt5_AVAILABLE, reason="PyQt5 not available")
class TestVideoPlayer:
    """Test suite for VideoPlayer component."""
    
    @patch('main.ui.dialogs.video_player.QMediaPlayer')
    @patch('main.ui.dialogs.video_player.QMediaContent')
    def test_video_player_initialization(self, mock_media_content, mock_media_player):
        """Test that VideoPlayer initializes properly."""
        # Configure mocks
        mock_player_instance = MagicMock()
        mock_media_player.return_value = mock_player_instance
        
        # Create video player
        video_path = "/path/to/test/video.mp4"
        player = VideoPlayer(video_path)
        
        # Check that media player was created
        assert mock_media_player.called
        
        # Check that media content was set with correct path
        mock_media_content.assert_called_once()
        args, kwargs = mock_media_content.call_args
        assert video_path in str(args) or video_path in str(kwargs)
        
        # Verify player was configured
        assert mock_player_instance.setMedia.called
        assert player.is_playing is False
        
    @patch('main.ui.dialogs.video_player.QMediaPlayer')
    @patch('main.ui.dialogs.video_player.QMediaContent')
    def test_video_play_pause(self, mock_media_content, mock_media_player):
        """Test play/pause functionality."""
        # Configure mocks
        mock_player_instance = MagicMock()
        mock_media_player.return_value = mock_player_instance
        
        # Create video player
        video_path = "/path/to/test/video.mp4"
        player = VideoPlayer(video_path)
        
        # Initial state should be not playing
        assert player.is_playing is False
        
        # Test play
        player.play_video()
        assert mock_player_instance.play.called
        assert player.is_playing is True
        
        # Test pause
        player.pause_video()
        assert mock_player_instance.pause.called
        assert player.is_playing is False
        
    @patch('main.ui.dialogs.video_player.QMediaPlayer')
    @patch('main.ui.dialogs.video_player.QMediaContent')
    def test_video_stop_and_reset(self, mock_media_content, mock_media_player):
        """Test stop and reset functionality."""
        # Configure mocks
        mock_player_instance = MagicMock()
        mock_media_player.return_value = mock_player_instance
        
        # Create video player
        video_path = "/path/to/test/video.mp4"
        player = VideoPlayer(video_path)
        
        # Play video
        player.play_video()
        assert player.is_playing is True
        
        # Test stop
        player.stop_video()
        assert mock_player_instance.stop.called
        assert player.is_playing is False
        
        # Test reset
        player.reset_video()
        assert mock_player_instance.setPosition.called
        mock_player_instance.setPosition.assert_called_with(0)
        
    @patch('main.ui.dialogs.video_player.QMediaPlayer')
    @patch('main.ui.dialogs.video_player.QMediaContent')
    def test_video_position_duration(self, mock_media_content, mock_media_player):
        """Test position and duration handling."""
        # Configure mocks
        mock_player_instance = MagicMock()
        mock_player_instance.duration.return_value = 60000  # 60 seconds
        mock_player_instance.position.return_value = 30000  # 30 seconds
        mock_media_player.return_value = mock_player_instance
        
        # Create video player
        video_path = "/path/to/test/video.mp4"
        player = VideoPlayer(video_path)
        
        # Test duration
        duration = player.get_duration()
        assert duration == 60000
        
        # Test position
        position = player.get_position()
        assert position == 30000
        
        # Test formatted time
        formatted = player.format_time(45000)  # 45 seconds
        assert formatted == "00:45"
        
    @patch('main.ui.dialogs.video_player.QMediaPlayer')
    @patch('main.ui.dialogs.video_player.QMediaContent')
    def test_video_events(self, mock_media_content, mock_media_player):
        """Test media player event handling."""
        # Configure mocks
        mock_player_instance = MagicMock()
        mock_media_player.return_value = mock_player_instance
        
        # Create video player
        video_path = "/path/to/test/video.mp4"
        player = VideoPlayer(video_path)
        
        # Create tracking variables
        position_updated = False
        duration_changed = False
        state_changed = False
        media_status_changed = False
        
        # Connect signals
        def on_position_changed(position):
            nonlocal position_updated
            position_updated = True
            
        def on_duration_changed(duration):
            nonlocal duration_changed
            duration_changed = True
            
        def on_state_changed(state):
            nonlocal state_changed
            state_changed = True
            
        def on_media_status_changed(status):
            nonlocal media_status_changed
            media_status_changed = True
            
        # Connect signal handlers
        player.player.positionChanged.connect(on_position_changed)
        player.player.durationChanged.connect(on_duration_changed)
        player.player.stateChanged.connect(on_state_changed)
        player.player.mediaStatusChanged.connect(on_media_status_changed)
        
        # Simulate signal emissions
        player.player.positionChanged.emit(15000)
        player.player.durationChanged.emit(60000)
        player.player.stateChanged.emit(QMediaPlayer.PlayingState if PyQt5_AVAILABLE else 1)
        player.player.mediaStatusChanged.emit(QMediaPlayer.LoadedMedia if PyQt5_AVAILABLE else 2)
        
        # Check that signal handlers were called
        assert position_updated
        assert duration_changed
        assert state_changed
        assert media_status_changed
        
    @patch('main.ui.dialogs.video_player.QMediaPlayer')
    @patch('main.ui.dialogs.video_player.QMediaContent')
    def test_video_close(self, mock_media_content, mock_media_player):
        """Test closing the video player."""
        # Configure mocks
        mock_player_instance = MagicMock()
        mock_media_player.return_value = mock_player_instance
        
        # Create video player
        video_path = "/path/to/test/video.mp4"
        player = VideoPlayer(video_path)
        
        # Play video
        player.play_video()
        assert player.is_playing is True
        
        # Close player
        player.close()
        
        # Verify player was stopped
        assert mock_player_instance.stop.called