# 🍽️ Website Gợi Ý Món Ăn Theo Nguyên Liệu
**AWS Serverless Lab** · DynamoDB · Lambda · API Gateway · S3

---

## 👥 Phân Công Nhiệm Vụ

| Thành Viên | Phụ Trách Thư Mục | Nhiệm Vụ Chi Tiết |
|---|---|---|
| **Thành viên 1** | `frontend/` | Thiết kế UI, viết HTML/CSS/JS, tích hợp API URL, upload lên S3 |
| **Thành viên 2** | `backend/` | Tạo bảng DynamoDB, import dữ liệu, viết và deploy Lambda function |
| **Thành viên 3** | `security-and-docs/` | Cấu hình IAM Policy, tạo API Gateway, kiểm tra CORS, viết tài liệu |

---

## 🏗️ Kiến Trúc Hệ Thống

```
Người dùng
    │
    ▼
[S3 Static Website]  ←── frontend/index.html
    │
    │  HTTP GET /search?ingredients=trứng,cà chua
    ▼
[API Gateway]  ←── REST API (HTTP API)
    │
    │  Trigger
    ▼
[AWS Lambda]  ←── backend/lambda_function.py (Python 3.12)
    │
    │  boto3.scan()
    ▼
[DynamoDB: RecipesTable]  ←── dữ liệu từ backend/seed_data.json
```

---

## 🚀 Hướng Dẫn Triển Khai

### Bước 1 — Tạo Bảng DynamoDB (Thành viên 2)

1. Vào **AWS Console → DynamoDB → Create table**
2. Cấu hình bảng:
   - **Table name:** `RecipesTable`
   - **Partition key:** `RecipeID` (String)
3. Sau khi bảng tạo xong, vào tab **Items → Create item**
4. Import lần lượt 10 món từ file `backend/seed_data.json`
   - **Hoặc** dùng AWS CLI để import hàng loạt:
     ```bash
     # Tạo script import (chạy từng item)
     aws dynamodb put-item \
       --table-name RecipesTable \
       --item file://item.json \
       --region ap-southeast-1
     ```

---

### Bước 2 — Tạo IAM Role cho Lambda (Thành viên 3)

1. Vào **IAM → Roles → Create role**
2. **Trusted entity:** Lambda
3. Gắn policy từ file `security-and-docs/iam_policy.json`:
   - Vào **IAM → Policies → Create policy → JSON tab**
   - Paste nội dung file vào và đặt tên: `RecipesLambdaPolicy`
4. Gắn policy vừa tạo vào Role → đặt tên Role: `RecipesLambdaRole`

---

### Bước 3 — Tạo Lambda Function (Thành viên 2)

1. Vào **Lambda → Create function**
2. Cấu hình:
   - **Function name:** `RecipeSearchFunction`
   - **Runtime:** Python 3.12
   - **Execution role:** `RecipesLambdaRole` (đã tạo ở Bước 2)
3. Paste toàn bộ nội dung file `backend/lambda_function.py` vào code editor
4. Bấm **Deploy**
5. (Tùy chọn) Thêm **Environment Variables:**
   - `DYNAMODB_TABLE` = `RecipesTable`

---

### Bước 4 — Tạo API Gateway (Thành viên 3)

1. Vào **API Gateway → Create API → HTTP API**
2. Thêm Integration:
   - **Integration type:** Lambda
   - **Lambda function:** `RecipeSearchFunction`
3. Thêm Route:
   - `GET /search` → Integration vừa tạo
   - `OPTIONS /search` → Integration vừa tạo (cho CORS)
4. Cấu hình **CORS:**
   - **Allow origins:** `*`
   - **Allow methods:** `GET, OPTIONS`
   - **Allow headers:** `Content-Type`
5. **Deploy** → chọn stage `prod`
6. Sao chép **Invoke URL** (ví dụ: `https://abc123.execute-api.ap-southeast-1.amazonaws.com/prod`)

---

### Bước 5 — Cập Nhật Frontend và Upload lên S3 (Thành viên 1)

1. Mở file `frontend/index.html`
2. Tìm dòng:
   ```javascript
   const API_URL = "";
   ```
3. Điền Invoke URL từ Bước 4:
   ```javascript
   const API_URL = "https://abc123.execute-api.ap-southeast-1.amazonaws.com/prod/search";
   ```
4. Vào **S3 → Create bucket:**
   - **Bucket name:** `recipe-suggestion-website` *(phải là tên duy nhất toàn cầu)*
   - **Region:** `ap-southeast-1`
5. Tắt **Block all public access** → xác nhận
6. Vào tab **Properties → Static website hosting → Enable**
   - **Index document:** `index.html`
7. Vào tab **Permissions → Bucket policy** → Paste policy sau:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "PublicReadGetObject",
         "Effect": "Allow",
         "Principal": "*",
         "Action": "s3:GetObject",
         "Resource": "arn:aws:s3:::recipe-suggestion-website/*"
       }
     ]
   }
   ```
8. Upload file `frontend/index.html` lên bucket
9. Truy cập **Endpoint URL** của S3 static website để kiểm tra

---

## ✅ Kiểm Tra Hoàn Chỉnh

| Hạng mục | Cách kiểm tra | Kết quả mong đợi |
|---|---|---|
| DynamoDB | Vào Items → kiểm tra 10 món | Hiển thị đủ 10 bản ghi |
| Lambda | Test với event `{"queryStringParameters": {"ingredients": "trứng"}}` | Status 200, trả về JSON |
| API Gateway | Gọi URL trên trình duyệt | JSON trả về có `recipes` |
| S3 Website | Mở Endpoint URL | Trang web hiển thị, tìm kiếm hoạt động |
| CORS | Dùng DevTools Network tab | Không có lỗi CORS |
| CloudWatch | Lambda → Monitor → Logs | Thấy log `[START]`, `[SCAN]`, `[SUCCESS]` |

---

## 📁 Cấu Trúc Thư Mục

```
AWS-Project-Final/
├── frontend/
│   └── index.html          # Giao diện web (HTML5 + Tailwind + Vanilla JS)
├── backend/
│   ├── lambda_function.py  # Code Lambda Python 3.12
│   └── seed_data.json      # Dữ liệu 10 món ăn để import DynamoDB
└── security-and-docs/
    ├── iam_policy.json      # IAM Policy (Least Privilege)
    └── README.md            # File này
```

---

## 🔐 Nguyên Tắc Bảo Mật (Least Privilege)

- Lambda **chỉ** có quyền `Scan`, `Query`, `GetItem` trên **đúng bảng** `RecipesTable`
- Lambda **chỉ** ghi log vào `/aws/lambda/*` trên CloudWatch
- S3 bucket **chỉ** cho phép đọc file tĩnh (`s3:GetObject`)
- API Gateway có CORS headers nhưng giới hạn method (`GET`, `OPTIONS`)
- Input validation trong Lambda: giới hạn độ dài 200 ký tự, chặn ký tự injection

---

*Dự án AWS Serverless Lab — Nhóm thực hiện: Thành viên 1, Thành viên 2, Thành viên 3*
