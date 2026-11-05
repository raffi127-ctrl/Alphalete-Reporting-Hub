"""A 5xx on the upload or a network blip on the download costs a wait, not an ad."""
import unittest
import urllib.error
from unittest import mock

import requests

from automations.ad_photo_threads import post
from automations.sara_down import run as sara


def _http(code):
    return urllib.error.HTTPError("https://files.slack.com/x", code, "x", {}, None)


class Client:
    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    def files_upload_v2(self, **kw):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return {"files": [{"id": "F1"}]}


@mock.patch.object(post.time, "sleep")
class UploadRetry(unittest.TestCase):
    def test_504_then_ok_posts_once(self, _):
        cl = Client(_http(504))
        self.assertEqual(post.upload_with_retry(cl, channel="C")["files"][0]["id"], "F1")
        self.assertEqual(cl.calls, 2)

    def test_gives_up_after_three_tries(self, _):
        cl = Client(_http(504), _http(504), _http(504))
        with self.assertRaises(urllib.error.HTTPError):
            post.upload_with_retry(cl, channel="C")
        self.assertEqual(cl.calls, 3)

    def test_4xx_is_not_retried(self, _):
        cl = Client(_http(403))
        with self.assertRaises(urllib.error.HTTPError):
            post.upload_with_retry(cl, channel="C")
        self.assertEqual(cl.calls, 1)

    def test_timeout_is_not_retried_it_can_part_post(self, _):
        cl = Client(TimeoutError("read timed out"))
        with self.assertRaises(TimeoutError):
            post.upload_with_retry(cl, channel="C")
        self.assertEqual(cl.calls, 1)


class Resp:
    def __init__(self, code=200, content=b"x"):
        self.status_code, self.content = code, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@mock.patch.object(sara.time, "sleep")
class DownloadRetry(unittest.TestCase):
    def test_timeout_then_ok(self, _):
        with mock.patch.object(sara.requests, "get",
                               side_effect=[requests.ConnectionError("aborted"), Resp()]) as g:
            self.assertEqual(sara._download("u", "t"), b"x")
        self.assertEqual(g.call_count, 2)

    def test_500_then_ok(self, _):
        with mock.patch.object(sara.requests, "get", side_effect=[Resp(500), Resp()]) as g:
            self.assertEqual(sara._download("u", "t"), b"x")
        self.assertEqual(g.call_count, 2)

    def test_403_is_not_retried(self, _):
        with mock.patch.object(sara.requests, "get", return_value=Resp(403)) as g:
            with self.assertRaises(requests.HTTPError):
                sara._download("u", "t")
        self.assertEqual(g.call_count, 1)

    def test_network_failure_does_not_say_sign_in_page(self, _):
        with mock.patch.object(sara, "_tokens", return_value=[("user token", "t")]),                 mock.patch.object(sara.requests, "get",
                                  side_effect=requests.ConnectionError("aborted")):
            with self.assertRaises(sara.SaraDownError) as got:
                sara._download_image({"url_private": "u", "name": "a.png"})
        self.assertIn("network", str(got.exception))
        self.assertNotIn("files:read", str(got.exception))

    def test_html_page_still_says_files_read(self, _):
        with mock.patch.object(sara, "_tokens", return_value=[("user token", "t")]),                 mock.patch.object(sara.requests, "get", return_value=Resp(200, b"<html>")):
            with self.assertRaises(sara.SaraDownError) as got:
                sara._download_image({"url_private": "u", "name": "a.png"})
        self.assertIn("files:read", str(got.exception))


if __name__ == "__main__":
    unittest.main()
