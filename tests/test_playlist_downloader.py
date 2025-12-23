"""Tests for PlaylistDownloader functionality"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import pytest
import requests
from youtube_downloader.downloader import PlaylistDownloader, YouTubeDownloader


class TestPlaylistDownloader(unittest.TestCase):
    """Test cases for PlaylistDownloader"""

    def test_extract_playlist_id(self):
        """Test playlist ID extraction from various URL formats"""
        downloader = PlaylistDownloader("https://www.youtube.com/playlist?list=PLxxx")
        self.assertEqual(downloader.playlist_id, "PLxxx")
        
        downloader = PlaylistDownloader("https://www.youtube.com/playlist?list=PLabcdef")
        self.assertEqual(downloader.playlist_id, "PLabcdef")
        
        downloader = PlaylistDownloader("PLdirect")
        self.assertEqual(downloader.playlist_id, "PLdirect")
    
    def test_extract_playlist_id_invalid(self):
        """Test that invalid playlist URLs raise ValueError"""
        with self.assertRaises(ValueError):
            PlaylistDownloader("https://www.youtube.com/watch?v=VIDEO_ID")
        
        with self.assertRaises(ValueError):
            PlaylistDownloader("https://invalid.com/not@valid!")
    
    def test_concurrency_config(self):
        """Test that concurrency is properly configured"""
        downloader = PlaylistDownloader("https://www.youtube.com/playlist?list=PLxxx", concurrency=5)
        self.assertEqual(downloader.concurrency, 5)
        
        downloader = PlaylistDownloader("https://www.youtube.com/playlist?list=PLxxx", concurrency=1)
        self.assertEqual(downloader.concurrency, 1)
        
        # Test default
        downloader = PlaylistDownloader("https://www.youtube.com/playlist?list=PLxxx")
        self.assertEqual(downloader.concurrency, 3)
    
    def test_get_videos_empty_playlist(self):
        """Test handling of empty playlist"""
        downloader = PlaylistDownloader("https://www.youtube.com/playlist?list=PLxxx")
        
        with patch.object(downloader, '_get_playlist_info', return_value={'contents': {}}):
            with patch.object(downloader, '_extract_videos_from_playlist_info', return_value=[]):
                with self.assertRaises(Exception) as context:
                    downloader.get_videos()
                
                self.assertIn("No videos found", str(context.exception))
    
    def test_download_statistics(self):
        """Test that download returns proper statistics"""
        downloader = PlaylistDownloader("https://www.youtube.com/playlist?list=PLxxx", concurrency=1)
        
        # Mock videos
        mock_videos = [
            {'video_id': 'vid1', 'title': 'Video 1', 'url': 'https://www.youtube.com/watch?v=vid1'},
            {'video_id': 'vid2', 'title': 'Video 2', 'url': 'https://www.youtube.com/watch?v=vid2'}
        ]
        
        with patch.object(downloader, 'get_videos', return_value=mock_videos):
            with patch.object(downloader, '_download_single_video', return_value=True):
                with patch('youtube_downloader.downloader.os.makedirs'):
                    with patch('youtube_downloader.downloader.os.path.exists', return_value=False):
                        with patch('youtube_downloader.downloader.os.path.join', side_effect=lambda *args: '/'.join(args)):
                            stats = downloader.download(output_dir="./test")
                            
                            self.assertEqual(stats['total'], 2)
                            self.assertEqual(stats['successful'], 2)
                            self.assertEqual(stats['failed'], 0)
                            self.assertEqual(len(stats['failed_videos']), 0)


if __name__ == '__main__':
    unittest.main()


#############################
# Pytest-style added tests
#############################


def make_mock_response(status_code=200, content=b'', headers=None):
    class MockResponse:
        def __init__(self):
            self.status_code = status_code
            self._content = content
            self.headers = headers or {'content-length': str(len(content))}

        def raise_for_status(self):
            if 400 <= self.status_code:
                raise requests.exceptions.HTTPError(f"{self.status_code}")

        def json(self):
            # For tests that need JSON, caller will monkeypatch this explicitly
            return {}

        def iter_content(self, chunk_size=1024):
            # yield content in chunk_size blocks
            for i in range(0, len(self._content), chunk_size):
                yield self._content[i:i+chunk_size]

    return MockResponse()


def test_get_formats_parses_streaming_data(monkeypatch):
    # Prepare a fake _get_video_info payload
    fake_data = {
        'streamingData': {
            'formats': [
                {'itag': 18, 'qualityLabel': '360p', 'mimeType': 'video/mp4; codecs="..."', 'url': 'http://a', 'contentLength': '1234'},
            ],
            'adaptiveFormats': [
                {'itag': 140, 'quality': 'audio', 'mimeType': 'audio/mp4; codecs="..."', 'url': 'http://b', 'contentLength': '4321'}
            ]
        }
    }

    dl = YouTubeDownloader("https://www.youtube.com/watch?v=AAAAAAAAAAA")
    monkeypatch.setattr(YouTubeDownloader, '_get_video_info', lambda self: fake_data)

    formats = dl.get_formats()

    assert any(f['itag'] == 18 and f['has_video'] for f in formats)
    assert any(f['itag'] == 140 and f['has_audio'] for f in formats)


def test_download_writes_file_and_selects_quality(monkeypatch, tmp_path):
    # Prepare downloader with one combined format
    content = b'abcdef'
    fmt = {
        'itag': 99,
        'quality': '720p',
        'mime': 'video/mp4',
        'url': 'http://example/video',
        'has_video': True,
        'has_audio': True,
        'filesize': len(content)
    }

    dl = YouTubeDownloader("https://www.youtube.com/watch?v=BBBBBBBBBBB")
    monkeypatch.setattr(YouTubeDownloader, 'get_formats', lambda self: [fmt])

    # Mock session.get to return streaming response
    resp = make_mock_response(status_code=200, content=content, headers={'content-length': str(len(content))})
    # Ensure json is not used; set attributes used by download
    monkeypatch.setattr(dl.session, 'get', lambda *args, **kwargs: resp)

    out = tmp_path / "out.mp4"
    result = dl.download(str(out), itag=99)

    assert result == str(out)
    assert out.exists()
    assert out.read_bytes() == content


def test_get_formats_rate_limited_raises(monkeypatch):
    dl = YouTubeDownloader("https://www.youtube.com/watch?v=CCCCCCCCCCC")

    # Create a response object with 429 status
    class Resp429:
        status_code = 429
        def raise_for_status(self):
            raise requests.exceptions.HTTPError("429")

        def json(self):
            return {}

    monkeypatch.setattr(dl.session, 'post', lambda *a, **k: Resp429())

    with pytest.raises(Exception) as exc:
        dl.get_formats()

    assert 'Rate limited' in str(exc.value) or '429' in str(exc.value)


def test_get_video_info_network_error_propagates(monkeypatch):
    dl = YouTubeDownloader("https://www.youtube.com/watch?v=DDDDDDDDDDD")

    # Simulate a network timeout for every post
    def raise_timeout(*a, **k):
        raise requests.exceptions.Timeout('timed out')

    monkeypatch.setattr(dl.session, 'post', raise_timeout)

    with pytest.raises(requests.exceptions.Timeout):
        # call get_formats which calls _get_video_info
        dl.get_formats()


def test_playlist_get_videos_parses_response(monkeypatch):
    pd = PlaylistDownloader("https://www.youtube.com/playlist?list=PLTEST")

    fake_playlist = {
        'contents': {
            'twoColumnBrowseResultsRenderer': {
                'tabs': [
                    {
                        'tabRenderer': {
                            'content': {
                                'sectionListRenderer': {
                                    'contents': [
                                        {
                                            'itemSectionRenderer': {
                                                'contents': [
                                                    {
                                                        'playlistVideoRenderer': {
                                                            'videoId': 'vid1',
                                                            'title': {'runs': [{'text': 'First'}]}
                                                        }
                                                    },
                                                    {
                                                        'playlistVideoRenderer': {
                                                            'videoId': 'vid2',
                                                            'title': {'runs': [{'text': 'Second'}]}
                                                        }
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    }
                ]
            }
        }
    }

    monkeypatch.setattr(PlaylistDownloader, '_get_playlist_info', lambda self: fake_playlist)

    videos = pd.get_videos()
    assert len(videos) == 2
    assert videos[0]['video_id'] == 'vid1' and videos[0]['title'] == 'First'

