# Judge audit

Chạy:
- `python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5`
- `python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Fail rate (obs → corrected) | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 0.280 → 0.300 | Có (`PASS floors`) | Dùng |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 0.090 → 0.300 | Không (`FAIL floors`: κ & R dưới ngưỡng) | Loại |

> Ghi chú ký hiệu: `POS = "FAIL"` (mục tiêu của judge là phát hiện lỗi). Do đó, `FN` là ca hỏng thật (`human=FAIL`) nhưng judge bỏ sót (`judge=PASS`), còn `FP` là ca đạt (`human=PASS`) nhưng judge phạt nhầm (`judge=FAIL`).

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | `HL-015` (`helpful`): *"Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ."* | PASS | FAIL | Người | Sai số tiền hoàn (ledger ghi `40.000đ`); judge không có dữ liệu ledger nên chấm PASS (`FN`). |
| 2 | `HL-016` (`helpful`): *"Dạ, LogiX thành thật xin lỗi anh/chị... LogiX đã hoàn 55.000đ cho đơn O-404. Một lần nữa LogiX xin lỗi..."* | PASS | FAIL | Người | Sai số tiền hoàn (ledger ghi `35.000đ`), nhưng câu trả lời dài, xin lỗi nhiều lần đánh lừa judge (`FN` do verbosity bias). |
| 3 | `HL-020` (`helpful`): *"Dạ, LogiX đã hoàn 90.000đ cho đơn O-303 ạ."* | PASS | FAIL | Người | Sai số tiền hoàn (ledger ghi `120.000đ`); judge bỏ sót (`FN`). |
| 4 | `HL-047` (`helpful`): *"Ok bạn, đơn O-515 xử lý rồi nhé."* | PASS | FAIL | Người | Sai xưng hô (`"Ok bạn"`, `"nhé"`), thiếu lịch sự chuẩn CSKH nhưng judge vẫn cho PASS (`FN`). |
| 5 | `H-008` (`tone_ok`): *"Em đã hoàn tiền cho anh rồi nha, anh check giúp em."* | PASS | FAIL | Người | Xưng `"em"` + `"nha"`, suồng sã với khách; judge nhầm là thân thiện (`FN`). |
| 6 | `H-029` (`tone_ok`): *"Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm."* | PASS | FAIL | Người | Giọng ra lệnh (`"không cần nhắn thêm"`); judge chỉ bắt từ `"Dạ, vui lòng"` nên bỏ sót (`FN`). |
| 7 | `H-042` (`tone_ok`): *"Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ."* | FAIL | PASS | Người | Câu ngắn gọn, lịch sự, đủ thông tin nhưng judge phạt nhầm vì thiếu lời xin lỗi (`FP`). |
| 8 | `H-051` (`tone_ok`): *"Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ."* | FAIL | PASS | Người | Dùng từ `"refund"` được CS LogiX cho phép; judge phạt nhầm vì lẫn tiếng Anh (`FP`). |
| 9 | `H-081` (`tone_ok`): *"Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ."* | FAIL | PASS | Judge | Nhãn người đánh nhầm (đọc nhầm ticket); judge bắt đúng theo tiêu chí khắt khe hơn — cần rà lại nhãn mẫu này. |

## Kết luận

- **Tiêu chí bị loại (`helpful`) và lý do:**
  - Ma trận nhầm lẫn của `helpful` trên `n = 100` mẫu là `{'tp': 9, 'fp': 0, 'fn': 21, 'tn': 70}` (so với `tone_ok`: `{'tp': 24, 'fp': 4, 'fn': 6, 'tn': 66}`).
  - Tuy `Precision = 1.0` (không phạt oan ca nào, `fp = 0`), `helpful` có **`fn = 21` rất cao**, kéo **`Recall = 0.300`** (thấp hơn sàn `0.7`) và **`κ = 0.375`** (thấp hơn sàn `0.6`).
  - Nguyên nhân chính: judge quá dễ dãi / bỏ sót lỗi khi câu trả lời trình bày lịch sự hoặc dài dòng xin lỗi nhưng **sai số tiền hoàn so với ledger** (18/21 ca `FN`, đặc biệt các mẫu lặp lời xin lỗi như `HL-016`, `HL-028`, `HL-035`, `HL-041`, `HL-070`, `HL-090`) hoặc **sai xưng hô** (3/21 ca `FN`: `HL-047`, `HL-091`, `HL-097`). Kết quả là tỷ lệ lỗi quan sát bị đánh giá thấp giả tạo (`0.090` so với mức hiệu chỉnh Rogan–Gladen `0.300`), không đủ tin cậy để chấm hệ thống.
- **Đề xuất sửa rubric & quy trình chấm:**
  1. **Tách kiểm tra sự thật (factual/amount correctness) khỏi LLM judge `helpful`:** Kiểm tra số tiền hoàn, mã đơn và trạng thái giao dịch bằng đối chiếu tất định (deterministic check) với ledger/tool output trước, không để LLM judge chỉ nhìn văn bản trả lời đoán `PASS`.
  2. **Chống verbosity bias trong rubric `helpful`:** Nêu rõ trong prompt rằng lời xin lỗi dài dòng hoặc lặp lại **không** bù đắp được cho việc thiếu thông tin hoặc sai dữ kiện; bắt buộc chấm `FAIL` với văn phong suồng sã (`"Ok bạn"`, `"nhé"`).
  3. **Tinh chỉnh rubric `tone_ok` (tùy chọn cho vòng sau):** Cho phép thuật ngữ `"refund"` theo chuẩn CS LogiX (`H-051`), không bắt buộc xin lỗi với câu thông báo đã hoàn tiền chuẩn mực (`H-042`), đồng thời siết lỗi hứa hẹn ngoài kết quả hệ thống (`H-063`), emoji (`H-070`), và tiếng Việt mất dấu (`H-094`).
- **Rủi ro còn lại:**
  - Cả hai bộ judge chỉ mới được hiệu chỉnh trên dữ liệu replay đã công khai (`judge_tone_public.csv`, `judge_helpful_public.csv`); nếu tối ưu rubric trực tiếp trên bộ này có nguy cơ overfit vào các mẫu lỗi đã biết. Cần thu thập thêm tập **held-out thật** được gán nhãn người mới độc lập trước khi đưa judge vào cổng đánh giá chính thức.
