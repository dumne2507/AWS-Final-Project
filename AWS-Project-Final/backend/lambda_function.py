"""
AWS Lambda Function — GỢI Ý MÓN ĂN THEO NGUYÊN LIỆU
Runtime  : Python 3.12
DynamoDB : RecipesTable
Handler  : lambda_function.lambda_handler
"""

import json
import boto3
import os
import logging
from botocore.exceptions import ClientError

# ─────────────────────────────────────────────
#  Logger — ghi ra CloudWatch
# ─────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────
TABLE_NAME        = os.environ.get("DYNAMODB_TABLE", "RecipesTable")
MAX_INPUT_LENGTH  = 200     # Giới hạn độ dài input chống spam
MAX_KEYWORDS      = 10      # Tối đa 10 nguyên liệu mỗi lần tìm

# ─────────────────────────────────────────────
#  CORS headers — bắt buộc cho API Gateway
# ─────────────────────────────────────────────
CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Content-Type":                 "application/json"
}

# ─────────────────────────────────────────────
#  DynamoDB client (module-level để tái sử dụng)
# ─────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "ap-southeast-1"))
table    = dynamodb.Table(TABLE_NAME)


# ─────────────────────────────────────────────
#  Helper: chuẩn hoá response
# ─────────────────────────────────────────────
def make_response(status_code: int, body: dict) -> dict:
    """Tạo response chuẩn cho API Gateway."""
    return {
        "statusCode": status_code,
        "headers":    CORS_HEADERS,
        "body":       json.dumps(body, ensure_ascii=False)
    }


# ─────────────────────────────────────────────
#  Helper: validate input
# ─────────────────────────────────────────────
def validate_input(raw_input: str) -> tuple[bool, str]:
    """
    Kiểm tra đầu vào người dùng.
    Trả về (is_valid, error_message).
    """
    if not raw_input:
        return False, "Thiếu tham số 'ingredients'."

    raw_input = raw_input.strip()

    if len(raw_input) > MAX_INPUT_LENGTH:
        return False, (
            f"Input quá dài ({len(raw_input)} ký tự). "
            f"Tối đa {MAX_INPUT_LENGTH} ký tự."
        )

    # Chặn ký tự đặc biệt nguy hiểm (injection phòng ngừa)
    forbidden = ["<", ">", "{", "}", "$", "`", "\\", ";", "--"]
    for char in forbidden:
        if char in raw_input:
            return False, f"Input chứa ký tự không hợp lệ: '{char}'."

    return True, ""


# ─────────────────────────────────────────────
#  Core: quét DynamoDB và lọc theo nguyên liệu
# ─────────────────────────────────────────────
def scan_and_filter(keywords: list[str]) -> list[dict]:
    """
    Quét toàn bộ RecipesTable và lọc các món có chứa
    ít nhất một trong các nguyên liệu (keywords).
    """
    print(f"[SCAN] Bắt đầu quét DynamoDB table: {TABLE_NAME}")
    print(f"[SCAN] Keywords: {keywords}")

    response = table.scan()
    items    = response.get("Items", [])

    # DynamoDB phân trang — tiếp tục nếu còn dữ liệu
    while "LastEvaluatedKey" in response:
        print("[SCAN] Phân trang — đang tải thêm dữ liệu...")
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    print(f"[SCAN] Tổng số món trong bảng: {len(items)}")

    # Lọc: món khớp ít nhất 1 nguyên liệu
    matched = []
    for item in items:
        db_ingredients = [ing.lower() for ing in item.get("Ingredients", [])]
        for kw in keywords:
            if any(kw.lower() in ing for ing in db_ingredients):
                matched.append(item)
                break   # Tránh thêm trùng lặp

    print(f"[FILTER] Số món khớp: {len(matched)}")
    return matched


# ─────────────────────────────────────────────
#  MAIN HANDLER
# ─────────────────────────────────────────────
def lambda_handler(event, context):
    """
    Entry point của Lambda.
    Query params:
        - ingredients : string, phân cách bằng dấu phẩy (vd: "trứng,cà chua")
        - random      : "true" → trả về tất cả món (frontend tự shuffle)
    """
    print("=" * 60)
    print(f"[START] Lambda invoked | RequestId: {context.aws_request_id}")
    print(f"[EVENT] {json.dumps(event, ensure_ascii=False)}")

    # ── Xử lý CORS preflight OPTIONS ──
    http_method = event.get("httpMethod", "GET")
    if http_method == "OPTIONS":
        print("[CORS] Xử lý preflight OPTIONS request.")
        return make_response(200, {"message": "CORS OK"})

    try:
        # ── Lấy query parameters ──
        query_params = event.get("queryStringParameters") or {}
        raw_ingredients = query_params.get("ingredients", "").strip()
        is_random       = query_params.get("random", "false").lower() == "true"

        print(f"[PARAMS] ingredients='{raw_ingredients}', random={is_random}")

        # ── Chế độ ngẫu nhiên: trả về toàn bộ bảng ──
        if is_random:
            print("[RANDOM] Chế độ ngẫu nhiên — quét toàn bộ bảng.")
            response = table.scan()
            items    = response.get("Items", [])
            print(f"[RANDOM] Trả về {len(items)} món.")
            return make_response(200, {
                "recipes": items,
                "count":   len(items),
                "source":  "dynamodb-random"
            })

        # ── Validate input ──
        is_valid, error_msg = validate_input(raw_ingredients)
        if not is_valid:
            print(f"[VALIDATE] Lỗi validation: {error_msg}")
            return make_response(400, {"error": error_msg})

        # ── Parse keywords ──
        keywords = [kw.strip() for kw in raw_ingredients.split(",") if kw.strip()]
        keywords = keywords[:MAX_KEYWORDS]   # Giới hạn số lượng từ khoá
        print(f"[KEYWORDS] Parsed: {keywords}")

        if not keywords:
            return make_response(400, {"error": "Không có nguyên liệu hợp lệ sau khi xử lý."})

        # ── Quét và lọc DynamoDB ──
        matched_recipes = scan_and_filter(keywords)

        # ── Thành công ──
        print(f"[SUCCESS] Trả về {len(matched_recipes)} món ăn.")
        print("=" * 60)
        return make_response(200, {
            "recipes":  matched_recipes,
            "count":    len(matched_recipes),
            "keywords": keywords,
            "source":   "dynamodb"
        })

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg  = e.response["Error"]["Message"]
        print(f"[DYNAMODB ERROR] Code: {error_code} | Message: {error_msg}")
        logger.error(f"DynamoDB ClientError: {error_code} - {error_msg}", exc_info=True)
        return make_response(500, {
            "error":   "Lỗi kết nối DynamoDB.",
            "details": error_msg
        })

    except Exception as e:
        print(f"[UNHANDLED ERROR] {type(e).__name__}: {str(e)}")
        logger.error("Unhandled exception", exc_info=True)
        return make_response(500, {
            "error":   "Lỗi nội bộ máy chủ.",
            "details": str(e)
        })
