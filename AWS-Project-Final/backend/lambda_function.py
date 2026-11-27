"""
AWS Lambda Function — GỢI Ý MÓN ĂN THEO NGUYÊN LIỆU (HYBRID DYNAMODB + BEDROCK AI)
Runtime  : Python 3.12
DynamoDB : RecipesTable
AI       : Amazon Bedrock (Converse API)
Handler  : lambda_function.lambda_handler
"""

import json
import base64
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
AWS_REGION        = os.environ.get("AWS_REGION", "ap-southeast-1")
TABLE_NAME        = os.environ.get("DYNAMODB_TABLE", "RecipesTable")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "apac.anthropic.claude-haiku-4-5-20251001-v1:0")
MAX_INPUT_LENGTH  = 200     # Giới hạn độ dài input chống spam
MAX_KEYWORDS      = 10      # Tối đa 10 nguyên liệu mỗi lần tìm

# ─────────────────────────────────────────────
#  CORS headers — hỗ trợ HTTP API POST /suggest
# ─────────────────────────────────────────────
CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key",
    "Access-Control-Allow-Methods": "POST,GET,OPTIONS",
    "Content-Type":                 "application/json"
}

# ─────────────────────────────────────────────
#  AWS Clients (module-level để tái sử dụng)
# ─────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table    = dynamodb.Table(TABLE_NAME)
bedrock  = boto3.client("bedrock-runtime", region_name=AWS_REGION)


# ─────────────────────────────────────────────
#  Helper: chuẩn hoá response
# ─────────────────────────────────────────────
def make_response(status_code: int, body: dict) -> dict:
    """Tạo response chuẩn cho API Gateway HTTP API."""
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
        return False, "Vui lòng nhập ít nhất một nguyên liệu."

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
#  Core 1: quét DynamoDB tìm món có sẵn làm ngữ cảnh
# ─────────────────────────────────────────────
def scan_dynamodb_context(keywords: list[str]) -> list[str]:
    """
    Quét RecipesTable để lấy tên các món ăn khớp nguyên liệu (nếu có),
    vừa tận dụng dữ liệu có sẵn vừa kích hoạt luồng đọc DynamoDB (SSE-KMS).
    """
    try:
        response = table.scan()
        items    = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        matched_names = []
        for item in items:
            db_ingredients = [ing.lower() for ing in item.get("Ingredients", [])]
            for kw in keywords:
                if any(kw.lower() in ing for ing in db_ingredients):
                    dish_name = item.get("RecipeName") or item.get("Name") or ""
                    if dish_name:
                        matched_names.append(dish_name)
                    break

        print(f"[DYNAMODB] Tìm thấy {len(matched_names)} món tham khảo: {matched_names}")
        return matched_names
    except Exception as db_err:
        # Nếu bảng trống hoặc chưa có quyền đọc, vẫn cho phép AI Bedrock hoạt động bình thường
        print(f"[DYNAMODB WARNING] Bỏ qua bước đọc bảng: {db_err}")
        return []


# ─────────────────────────────────────────────
#  Core 2: gọi Amazon Bedrock gợi ý công thức
# ─────────────────────────────────────────────
def generate_ai_recipes(raw_ingredients: str, db_dishes: list[str]) -> str:
    """Gọi Amazon Bedrock Converse API để tạo công thức món ăn Việt Nam."""
    if MODEL_ID == "PASTE_YOUR_MODEL_ID_HERE" or not MODEL_ID.strip():
        raise ValueError("Chưa cấu hình MODEL_ID trong lambda_function.py.")

    context_note = ""
    if db_dishes:
        context_note = (
            f"Trong cơ sở dữ liệu nội bộ hiện có sẵn các món gợi ý sau: {', '.join(db_dishes[:5])}. "
            "Bạn có thể ưu tiên phát triển công thức từ các món này hoặc đề xuất món mới phù hợp hơn. "
        )

    prompt = (
        f"Tôi đang có các nguyên liệu sau: {raw_ingredients}. "
        f"{context_note}"
        "Hãy gợi ý 2 món ăn Việt Nam ngon, dễ nấu từ các nguyên liệu này. "
        "Trình bày rõ ràng bằng tiếng Việt theo cấu trúc cho từng món:\n"
        "**Tên món ăn**\n"
        "- Nguyên liệu cần chuẩn bị (ghi rõ nguyên liệu sẵn có và gia vị/nguyên liệu cần thêm)\n"
        "- Các bước chế biến chính (ngắn gọn, dễ làm)\n"
        "Không cần lời chào mở đầu hay kết thúc dài dòng."
    )

    print(f"[BEDROCK] Đang gọi model: {MODEL_ID}")
    response = bedrock.converse(
        modelId=MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}]
            }
        ],
        inferenceConfig={
            "maxTokens": 900,
            "temperature": 0.7
        }
    )

    return response["output"]["message"]["content"][0]["text"]


# ─────────────────────────────────────────────
#  MAIN HANDLER
# ─────────────────────────────────────────────
def lambda_handler(event, context):
    print("=" * 60)
    print(f"[START] Lambda invoked | RequestId: {context.aws_request_id}")

    # Hỗ trợ cả HTTP API (v2.0) và REST API (v1.0)
    http_method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "POST"
    )

    if http_method == "OPTIONS":
        print("[CORS] Xử lý preflight OPTIONS request.")
        return make_response(200, {"message": "CORS OK"})

    try:
        # ── Đọc body từ POST request ──
        raw_body = event.get("body") or ""
        if event.get("isBase64Encoded") and raw_body:
            raw_body = base64.b64decode(raw_body).decode("utf-8")

        body_data = json.loads(raw_body) if raw_body else {}
        query_params = event.get("queryStringParameters") or {}

        raw_ingredients = (
            body_data.get("ingredients")
            or query_params.get("ingredients")
            or ""
        ).strip()

        print(f"[INPUT] ingredients='{raw_ingredients}'")

        # ── Validate input ──
        is_valid, error_msg = validate_input(raw_ingredients)
        if not is_valid:
            print(f"[VALIDATE] Từ chối input: {error_msg}")
            return make_response(400, {"error": error_msg})

        keywords = [kw.strip() for kw in raw_ingredients.split(",") if kw.strip()][:MAX_KEYWORDS]

        # ── Bước 1: Lấy ngữ cảnh từ DynamoDB ──
        db_dishes = scan_dynamodb_context(keywords)

        # ── Bước 2: Gọi Amazon Bedrock tạo công thức ──
        ai_suggestion = generate_ai_recipes(raw_ingredients, db_dishes)

        source_label = (
            "AWS DynamoDB + Bedrock AI" if db_dishes else "AWS Bedrock AI"
        )

        print(f"[SUCCESS] Hoàn tất gợi ý | Source: {source_label}")
        print("=" * 60)

        return make_response(200, {
            "source":     source_label,
            "suggestion": ai_suggestion,
            "keywords":   keywords
        })

    except json.JSONDecodeError:
        return make_response(400, {"error": "Dữ liệu gửi lên không đúng định dạng JSON."})

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg  = e.response["Error"]["Message"]
        print(f"[AWS CLIENT ERROR] {error_code}: {error_msg}")
        logger.error(f"AWS ClientError: {error_code} - {error_msg}", exc_info=True)
        return make_response(500, {
            "error": f"Lỗi dịch vụ AWS ({error_code}): {error_msg}"
        })

    except Exception as e:
        print(f"[UNHANDLED ERROR] {type(e).__name__}: {str(e)}")
        logger.error("Unhandled exception", exc_info=True)
        return make_response(500, {
            "error": str(e)
        })
