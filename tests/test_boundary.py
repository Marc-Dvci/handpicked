"""The code/model boundary and the photo's privacy, checked on the requests themselves."""
import asyncio
import io
import json

import httpx
import pytest
from PIL import Image

from handpicked import config, hands, llm
from handpicked.service import SAMPLE_SHORTLIST, Handpicked

FREE_TEXT = "Selling my oval, a touch under a carat (0.92 ct), it measures 8.1 by 5.6 by 3.4 mm. Asking $2,450."


@pytest.fixture(scope="module")
def svc_and_requests(tmp_path_factory):
    s = config.load()
    s.var = tmp_path_factory.mktemp("var")
    s.youcam_key = s.dashscope_key = None
    svc = Handpicked(s)
    sent = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        sent.append(body)
        user = body["messages"][1]["content"]
        if '"draft"' in user:   # the verdict: reword with a number that is not in the facts
            out = "The oval looks 40% larger for far less."
        else:
            out = json.dumps({"measurements": {"value": {"length": 8.1, "width": 5.6, "depth": 3.4},
                                               "quote": "8.1 by 5.6 by 3.4 mm"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": out}}], "usage": {"total_tokens": 50}})

    svc.model = llm.DashScope("test-key", svc.budget, transport=httpx.MockTransport(handler))
    yield svc, sent
    svc.close()


def test_photos_never_reach_the_model(svc_and_requests):
    svc, sent = svc_and_requests
    board = asyncio.run(svc.compare("hand-1", [SAMPLE_SHORTLIST[0], FREE_TEXT]))
    asyncio.run(svc.tryon("hand-1", "oval", 5.62, "platinum", False, "s"))      # a recorded render
    assert sent, "the model was asked to read the free-text listing"
    for body in sent:
        for m in body["messages"]:
            assert isinstance(m["content"], str)
            assert "/9j/" not in m["content"] and "data:image" not in m["content"] and "base64" not in m["content"]
    assert board["readings"][1]["status"] == "ready"


def test_model_sentence_with_a_new_number_is_replaced_by_the_rules(svc_and_requests):
    svc, _ = svc_and_requests
    board = asyncio.run(svc.compare("hand-1", SAMPLE_SHORTLIST))
    assert board["verdict"]["source"] == "template" and board["verdict"]["model_refused"]
    assert "40%" not in board["verdict"]["text"]


def test_upload_is_stored_without_exif():
    im = Image.new("RGB", (64, 48), (200, 180, 160))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"          # Make
    exif[0x8825] = {2: (48.0, 35.0, 0.0)}  # GPS latitude
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    assert Image.open(io.BytesIO(buf.getvalue())).getexif()
    stored, _, _ = hands.normalise(buf.getvalue())
    assert not Image.open(io.BytesIO(stored)).getexif()
