# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11` (`run_id`: `R-seeded_regression-C-002-s11`) |
| Triệu chứng | `lab8` grader fail (`status resolved != denied`): ledger ghi `refund_vnd=20000`, `refund_count=1` và event 6 `reply` nói `"Dạ, LogiX đã hoàn 20.000đ cho đơn O-202."`, trong khi nhãn `C-002` yêu cầu `status=denied`, `refund_vnd=0`, `refund_count=0`. |
| Bước sai đầu tiên | Event 3 `model_override`: `{"delay_days": 5}` (tin số ngày trong ticket `"Đơn giao trễ 5 ngày"` thay vì `delay_days=2` từ DB). |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng hợp đồng (`principal_scope="owner_order_only"`, chỉ cấp tool read-only); event 2 `investigator` đọc đúng DB cho `O-202` với `delay_days=2`, `shipping_fee_vnd=20000`, `status="delivered"`. Mọi tính toán sai ở event 4 `quote` (`20000`) và chi tiền sau đó đều bắt nguồn từ event 3. |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) trong `docs/failure_taxonomy.md` |
| Đối chứng | Trên `fixed C-002@11` (`R-fixed-C-002-s11`), event 1–2 giống hệt, **không có** event `model_override`; event 3 là `quote {"amount_vnd": 0, "reason": "no_entitlement", "clause_ids": [], "parts": {}}`, event 4 `reply` từ chối và `lab8_pass=True`. |
| Regression test | `test_c002_seed11_rejects_ticket_override` trong `src/tests/test_lab9_trace_case.py` (assert `model_override` xuất hiện & `lab8_pass is False` trên `seeded_regression`, không xuất hiện & `lab8_pass is True` trên `fixed`; bắt thêm ở mức step bởi `DbFactKept` / `db_fact_kept`). |
| Chưa chắc chắn | Trace được chạy qua `MockLLM` trên 1 claim (`C-002@11`), chưa chứng minh mọi biến thể `FM-03` đều để lại event `model_override` (ví dụ `quiet_override` trong `variant_agent.py` bỏ qua bước ghi `model_override` nhưng vẫn bị `TrialPass`/`RefundAmountCorrect` bắt ở outcome). |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
