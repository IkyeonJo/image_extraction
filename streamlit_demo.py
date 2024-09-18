import cv2
import urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
import numpy as np
import pandas as pd
import os
from io import BytesIO
import re
from collections import Counter
import streamlit as st

# 사이드바 info
st.sidebar.info(
    """
Wishket 유사 이미지 추출 웹 데모
"""
)

# 추가 정보 또는 설명 (선택 사항)
st.sidebar.markdown(
    """
---
**🔖  참고 사항**

- 이 웹앱은 단순한 예시입니다. 😄
  - 위시캣에 업로드하신 **shoppling_prod_bluk_edit_20240731134629.xlsx** 파일을 업로드하는 것으로 가정하였습니다.
  - 엑셀파일 업로드 -> '결과보기' 버튼 클릭해 결과를 확인하실 수 있습니다.
  - url이 잘못된 이미지의 경우, **이미지 로드 실패**라는 메시지가 뜹니다.
- 주로 OpenCV라는 컴퓨터 비전(Computer Vision) 라이브러리를 통해 구현되었습니다.
  - 추후 머신러닝/인공지능 모델 채용과 다양한 테스트를 통해 최적의 유사 이미지를 추출할 수 있도록 고도화해 드리겠습니다.
- 고객과 세부 요건 협의 후, 웹앱 및 백엔드(DB) 추가, 이미지 편집을 위한 추가 기능을 구현해 드리겠습니다.
- 고객 경험이 최대화될 수 있도록 UI/UX 개선 작업을 수행하겠습니다. 👩🏻‍💻🙇🏻‍♂️
"""
)

# Streamlit 웹페이지 제목 및 설명 설정
st.title("유사 이미지 추출 웹 데모")
st.write("[기능 요약] 썸네일을 기준으로, 상세페이지에서 유사 이미지를 찾아 캡쳐합니다.")

# 파일 업로드 받기 (엑셀 파일)
uploaded_file = st.file_uploader(
    "👇 썸네일 및 상세페이지 이미지 url이 포함된 엑셀 파일을 업로드하세요",
    type=["xlsx"],
)

OUTPUT_DIR = "output_images"  # 최종 이미지 저장 디렉토리


# 엑셀 파일에서 데이터 읽기
def extract_image_urls_from_excel(excel_data):
    df = pd.read_excel(excel_data, engine="openpyxl")
    rows = []

    for _, row in df.iterrows():
        # "상세설명"에서 src 속성 추출 (큰 따옴표와 작은 따옴표 모두 지원)
        detail_html = row["상세설명"].strip()
        src_match = re.search(r'<img.*?src=[\'"](.*?)[\'"]', detail_html)
        image_url = src_match.group(1).strip() if src_match else None

        # "대표이미지(오픈마켓)"는 이미 URL로 저장된 값
        base_image_url = row["대표이미지(오픈마켓)"].strip()

        # "자사상품코드"는 저장할 파일명
        filename = row["자사상품코드"].strip() + ".jpg"

        if image_url and base_image_url and filename:
            rows.append((image_url, base_image_url, filename))

    return rows


# 이미지를 로드하는 함수 (웹 URL과 로컬 파일 모두 지원)
def load_image(path):
    try:
        if path.startswith("http"):
            temp_file = "temp_image.jpg"
            urllib.request.urlretrieve(path, temp_file)

            img = Image.open(temp_file)
            img = img.convert("RGB")

            os.remove(temp_file)
            return img
        else:
            if os.path.exists(path):
                img = Image.open(path)
                img = img.convert("RGB")
                return img
            else:
                st.warning(f"Error: 로컬 이미지 파일을 찾을 수 없습니다 - {path}")
                return None
    except Exception as e:
        st.warning(f"Error: 이미지 로드 실패 - {path}\n{str(e)}")
        return None


# 이미지 분할 함수 정의
def split_image_with_min_height_constraint(image, padding=20):
    gray = image.convert("L")
    gray_np = np.array(gray)

    v = np.median(gray_np)
    sigma = 0.33
    lower = int(max(0, (1.0 - sigma) * v))
    upper = int(min(255, (1.0 + sigma) * v))

    edges = cv2.Canny(gray_np, lower, upper)

    height, width = gray_np.shape
    min_section_height = height / 20

    row_sums = np.sum(edges, axis=1)
    sections = []
    in_section = False
    section_start = 0

    for i in range(1, height):
        if row_sums[i] < 100:
            if in_section:
                section_end = i
                if (section_end - section_start) >= min_section_height:
                    sections.append((section_start, section_end))
                in_section = False
        else:
            if not in_section:
                section_start = i
                in_section = True

    if in_section and (height - section_start) >= min_section_height:
        sections.append((section_start, height))

    section_images = []
    for i, (y1, y2) in enumerate(sections):
        y1_padded = max(0, y1 - padding)
        y2_padded = min(height, y2 + padding)

        if (y2_padded - y1_padded) >= min_section_height:
            section_image = image.crop((0, y1_padded, width, y2_padded))
            section_images.append(section_image)

    return section_images


# 두 이미지의 히스토그램을 비교하는 함수 정의
def compare_images(base_image, target_image):
    def calculate_histogram(image):
        hsv_image = image.convert("HSV")
        hist = np.histogram(np.array(hsv_image), bins=50, range=(0, 255))[0]
        hist = hist / hist.sum()
        return hist

    base_hist = calculate_histogram(base_image)
    target_hist = calculate_histogram(target_image)

    similarity_scores = {
        "Correlation": np.corrcoef(base_hist, target_hist)[0, 1],
        "Chi-Square": np.sum(
            (base_hist - target_hist) ** 2 / (base_hist + target_hist + 1e-10)
        ),
        "Intersection": np.minimum(base_hist, target_hist).sum(),
        "Bhattacharyya": np.sqrt(1 - np.sum(np.sqrt(base_hist * target_hist))),
    }

    return similarity_scores


def find_and_save_most_similar_image(base_image_url, detail_image_url, filename):
    base_image = load_image(base_image_url)
    detail_image = load_image(detail_image_url)

    if base_image is None or detail_image is None:
        st.warning(
            f"Error: 이미지 로드 실패 - {base_image_url} 또는 {detail_image_url}"
        )
        return None

    section_images = split_image_with_min_height_constraint(detail_image)

    similarity_votes = {
        "Correlation": {},
        "Chi-Square": {},
        "Intersection": {},
        "Bhattacharyya": {},
    }

    for i, section_image in enumerate(section_images):
        similarity_scores = compare_images(base_image, section_image)
        for method, score in similarity_scores.items():
            similarity_votes[method][i] = score

    best_matches = []
    for method, scores in similarity_votes.items():
        if method in ["Correlation", "Intersection"]:
            best_image_idx = max(scores, key=scores.get)
        else:
            best_image_idx = min(scores, key=scores.get)
        best_matches.append(best_image_idx)

    best_image_idx = Counter(best_matches).most_common(1)[0][0]
    most_similar_image = section_images[best_image_idx]

    resized_image = most_similar_image.resize((200, 200), Image.Resampling.LANCZOS)
    padded_image = ImageOps.expand(resized_image, border=20, fill="white")

    draw = ImageDraw.Draw(padded_image)
    font = ImageFont.load_default()
    file_name_without_extension = os.path.splitext(filename)[0]

    text_bbox = draw.textbbox((0, 0), file_name_without_extension, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    text_position = (
        (padded_image.width - text_width) // 2,
        padded_image.height - text_height - 10,
    )
    draw.text(text_position, file_name_without_extension, font=font, fill="black")

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    output_path = os.path.join(OUTPUT_DIR, filename)
    padded_image.save(output_path)
    return output_path


# 이미지 크기를 200x200으로 줄이는 함수
def resize_image(image, size=(200, 200)):
    return image.resize(size, Image.Resampling.LANCZOS)


# 모든 이미지들을 200x200으로 줄인 후 결합
def merge_images(image_paths):
    images = []
    for path in image_paths:
        try:
            img = Image.open(path)
            resized_img = resize_image(img)
            images.append(resized_img)
        except Exception as e:
            st.error(f"Error: 이미지를 불러오는 중 오류 발생 - {path}\n{str(e)}")

    if not images:
        st.warning("Error: 결합할 이미지가 없습니다.")
        return

    num_images = len(images)
    grid_size = int(np.ceil(np.sqrt(num_images)))
    new_im = Image.new("RGB", (grid_size * 240, grid_size * 240), "white")

    x_offset = 0
    y_offset = 0
    for i, img in enumerate(images):
        new_im.paste(img, (x_offset, y_offset))
        x_offset += 240
        if x_offset >= grid_size * 240:
            x_offset = 0
            y_offset += 240

    new_im.save("all_merged.jpg")
    return new_im


# 엑셀 파일이 업로드되면 처리
if uploaded_file:
    if st.button("결과보기"):
        rows = extract_image_urls_from_excel(uploaded_file)

        progress_text = "유사 이미지 추출에 시간이 다소 걸립니다. 잠시 기다려 주십시오."
        progress_bar = st.progress(0)  # Progress Bar 추가
        total_rows = len(rows)

        saved_image_paths = []
        for index, (detail_image_url, base_image_url, filename) in enumerate(rows):
            try:
                output_path = find_and_save_most_similar_image(
                    base_image_url, detail_image_url, filename
                )
                if output_path:
                    saved_image_paths.append(output_path)
            except Exception as e:
                st.error(
                    f"Error: 행 처리 중 오류 발생 - {detail_image_url}, {base_image_url}\n{str(e)}"
                )
                continue  # 오류 발생 시 다음 행으로 넘어감

            # Progress Bar 업데이트
            progress_bar.progress((index + 1) / total_rows)

        if saved_image_paths:
            final_image = merge_images(saved_image_paths)
            st.markdown("---")  # 구분선 추가
            st.subheader("각 썸네일과 가장 유사한 이미지들의 묶음")
            st.image(
                final_image,
                caption="가장 유사한 이미지들의 묶음",
                use_column_width=True,
            )

            # 이미지 다운로드 버튼 추가
            with open("all_merged.jpg", "rb") as file:
                btn = st.download_button(
                    label="이미지 다운로드",
                    data=file,
                    file_name="all_merged.jpg",
                    mime="image/jpg",
                )

        # Progress Bar 완료
        progress_bar.progress(100)
