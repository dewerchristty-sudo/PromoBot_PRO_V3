import json
from io import BytesIO
from unittest.mock import patch

from bs4 import BeautifulSoup
from PIL import Image
import pytest

from src.core.notifier import LowResolutionImageError, Notifier
from src.stores.amazon import Amazon
from src.stores.amazon_images import (
    amazon_image_candidates,
    amazon_image_candidates_from_element,
    original_amazon_image_url,
)


BASE = "https://m.media-amazon.com/images/I/51Example"


def test_ac_ul320_generates_original_candidate():
    thumb = BASE + "._AC_UL320_.jpg"
    assert amazon_image_candidates((thumb,)) == [BASE + ".jpg", thumb]


def test_sx_and_sy_generate_original_candidate():
    for transform in ("_SX320_", "_SY320_"):
        thumb = BASE + f".{transform}.jpg"
        assert amazon_image_candidates((thumb,))[0] == BASE + ".jpg"


def test_srcset_selects_largest_image():
    values = amazon_image_candidates(
        srcset=f"{BASE}._SX320_.jpg 320w, {BASE}._SX1500_.jpg 1500w"
    )
    assert values[0] == BASE + ".jpg"
    assert values.index(BASE + "._SX1500_.jpg") < values.index(BASE + "._SX320_.jpg")


def test_old_hires_has_priority():
    hires = "https://m.media-amazon.com/images/I/hires.jpg"
    values = amazon_image_candidates(
        (BASE + "._AC_UL320_.jpg",), old_hires=hires,
        srcset=BASE + "._SX1500_.jpg 1500w",
    )
    assert values[0] == hires


def test_dynamic_image_selects_largest_dimensions():
    small = BASE + "._SX320_.jpg"
    large = BASE + "._SX1500_.jpg"
    values = amazon_image_candidates(
        dynamic_image=json.dumps({small: [320, 300], large: [1500, 1400]})
    )
    assert values.index(large) < values.index(small)


def test_non_amazon_urls_are_not_changed():
    for url in (
        "https://http2.mlstatic.com/D_NQ_NP_800.jpg",
        "https://down-br.img.susercontent.com/file/image@resize_w320_nl.webp",
    ):
        assert original_amazon_image_url(url) == url
        assert amazon_image_candidates((url,)) == [url]


def test_untransformed_amazon_url_remains_valid():
    url = BASE + ".jpg"
    assert amazon_image_candidates((url,)) == [url]


def test_duplicate_candidates_are_removed():
    thumb = BASE + "._AC_UL320_.jpg"
    values = amazon_image_candidates((thumb, thumb), old_hires=BASE + ".jpg")
    assert values == [BASE + ".jpg", thumb]


def test_element_uses_supported_amazon_attributes():
    html = (
        f'<img src="{BASE}._AC_UL320_.jpg" '
        f'data-old-hires="{BASE}.jpg" '
        f'srcset="{BASE}._SX320_.jpg 320w, {BASE}._SX1500_.jpg 1500w">'
    )
    image = BeautifulSoup(html, "lxml").select_one("img")
    assert amazon_image_candidates_from_element(image)[0] == BASE + ".jpg"


def image_bytes(size=(600, 600), image_format="JPEG"):
    output = BytesIO()
    Image.new("RGB", size, "white").save(output, format=image_format)
    return output.getvalue()


def test_failure_in_first_candidate_tries_next():
    thumb = BASE + "._AC_UL320_.jpg"
    notifier = Notifier()
    calls = []

    def download(url):
        calls.append(url)
        if url == BASE + ".jpg":
            raise ValueError("primeiro candidato indisponivel")
        return url, image_bytes()

    with patch.object(notifier, "download_image", side_effect=download):
        assert notifier.prepare_whatsapp_image(thumb).startswith(b"\xff\xd8")
    assert calls == [BASE + ".jpg", thumb]


def test_final_image_below_500_remains_rejected():
    notifier = Notifier()
    with patch.object(
        notifier, "download_image",
        return_value=(BASE + ".jpg", image_bytes((499, 700))),
    ):
        with pytest.raises(LowResolutionImageError):
            notifier.prepare_whatsapp_image(BASE + ".jpg")


def test_non_image_content_is_rejected():
    notifier = Notifier()
    with patch.object(
        notifier, "download_image",
        return_value=(BASE + ".jpg", b"<html>not an image</html>"),
    ):
        with pytest.raises(ValueError, match="imagem valida"):
            notifier.prepare_whatsapp_image(BASE + ".jpg")


def test_image_preparation_never_calls_evolution_api():
    notifier = Notifier()
    with (
        patch.object(
            notifier, "download_image",
            return_value=(BASE + ".jpg", image_bytes()),
        ),
        patch("src.core.notifier.requests.post") as post,
    ):
        notifier.prepare_whatsapp_image(BASE + "._AC_UL320_.jpg")
    post.assert_not_called()


def test_product_page_prefers_largest_dynamic_image():
    small = BASE + "._SX320_.jpg"
    large = BASE + "._SX1500_.jpg"
    html = f'''\
        <span id="productTitle">Produto Amazon</span>
        <span class="a-price"><span class="a-offscreen">R$ 1.234,56</span></span>
        <img id="landingImage" src="{small}"
             data-a-dynamic-image='{json.dumps({small: [320, 320], large: [1500, 1500]})}'>
        <meta property="og:image" content="https://example.com/og.jpg">
    '''

    product = Amazon().product_data_from_html(
        html, "https://www.amazon.com.br/dp/B0DZPGRMKM"
    )

    assert product["imagem"] == BASE + ".jpg"


def test_product_page_uses_twitter_image_before_json_ld():
    html = '''
        <span id="productTitle">Produto Amazon</span>
        <span class="a-price"><span class="a-offscreen">R$ 99,90</span></span>
        <meta name="twitter:image" content="https://example.com/twitter.jpg">
        <script type="application/ld+json">
          {"@type":"Product","image":"https://example.com/json.jpg"}
        </script>
    '''

    product = Amazon().product_data_from_html(
        html, "https://www.amazon.com.br/dp/B0DZPGRMKM"
    )

    assert product["imagem"] == "https://example.com/twitter.jpg"
