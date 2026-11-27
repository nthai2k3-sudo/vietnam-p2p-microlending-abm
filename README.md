# Vietnam P2P Micro-Lending: ABM + Smart Contract

Nguyên mẫu nghiên cứu học thuật gồm mô phỏng Agent-Based Modeling (Mesa 3.x) và hợp đồng Solidity cho V3. Đơn vị ABM là **triệu VNĐ**; hợp đồng dùng token VNĐ giả lập với 18 decimals.

## Kiến trúc

- **Off-chain ABM:** mô phỏng 500 tác nhân trong 60 tháng, so sánh V1/V2/V3 dưới cùng seed và cú sốc thu nhập ở tháng 30–35.
- **On-chain prototype:** `MockVNDT` và `P2PMicroLendingV3`. Hợp đồng quản lý pool, lãi suất kinked, ký quỹ và bảo lãnh.
- ABM là mô hình kinh tế, không phải oracle hay thành phần chạy trực tiếp trên blockchain. Các giả định hành vi (thu nhập, chi phí sống, ý định chiến lược) được mô phỏng off-chain.

## Cài đặt Python

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
python -m abm_simulation.run_experiment
```

Kết quả được lưu trong `outputs/`:
- `comparison_dashboard.png` (4 biểu đồ, 300 DPI)
- `summary.csv`
- `monthly_results.csv`

Mesa 3.x dùng `mesa.Agent`, `mesa.Model`, `mesa.DataCollector` và `model.agents.shuffle_do(...)`.

## Chạy Smart Contracts

Yêu cầu Node.js 18+.

```bash
cd smart_contracts
npm install
npx hardhat compile
npx hardhat run scripts/test_flow.js
```

Script chạy hai kịch bản độc lập: khoản vay được hoàn trả và khoản vay quá hạn được thanh lý. Script dùng Hardhat local network và token giả lập; không kết nối mainnet.

## Chạy dashboard tương tác

Dashboard gồm FastAPI/WebSocket để điều khiển Mesa và frontend React/Vite để quan sát 500 agent thật từ model.

Terminal 1:

```bash
.venv\Scripts\activate
python -m uvicorn backend.app.main:app --reload --port 8000
```

Terminal 2:

```bash
cd frontend
npm install
npm run dev
```

Mở `http://127.0.0.1:5173`. Swagger API ở `http://127.0.0.1:8000/docs`.
Dashboard hỗ trợ chọn V1/V2/V3, start/pause/step/reset, lọc agent, xem inspector và kết nối MetaMask.
Các thao tác blockchain thật vẫn chạy trên Hardhat local theo hướng dẫn ở trên; dashboard hiện chưa tự triển khai contract hay tự động đồng bộ event on-chain vào ABM.

## Quy ước và giả định mô hình

1. Một tháng ABM tương đương 30 ngày trong hợp đồng.
2. NPL = tổng gốc khoản vay đã bị ghi nhận vỡ nợ / tổng gốc đã giải ngân lũy kế. Đây là NPL theo cohort tích lũy, không phải tỷ lệ nợ xấu tại một thời điểm.
3. TVL mô phỏng = tiền mặt khả dụng + dư nợ còn được ghi nhận + ký quỹ/stake đang khóa. Khi khoản vay vỡ nợ, phần gốc được loại khỏi dư nợ và tổn thất được ghi nhận sau khi thu hồi ký quỹ/stake.
4. V1 không có ký quỹ; V2 có ký quỹ theo điểm uy tín; V3 hiện mô phỏng stake xã hội theo pool, tối đa 30% gốc khoản vay. V3 chưa mô hình hóa định danh guarantor, consent hoặc cạnh quan hệ như smart contract.
5. Lãi suất V2/V3 có sàn 1%/năm để tránh lãi suất âm do chiết khấu uy tín. Đây là ràng buộc triển khai bổ sung, không nằm trong công thức thô ban đầu.
6. Mô hình chiến lược là quy tắc hành vi đại diện, không phải nghiệm cân bằng trò chơi tổng quát. Tác nhân chiến lược có xu hướng trả các kỳ đầu rồi chọn vỡ nợ khi lợi ích giữ lại khoản vay vượt chi phí mất ký quỹ và tổn thất uy tín kỳ vọng.
7. Kết quả không được ép theo giả thuyết. V1 không nhất thiết cạn pool; V3 không nhất thiết phục hồi nếu nguồn cung vốn, khả năng trả nợ hoặc tỷ lệ bảo lãnh không đủ.

## Công thức

Utilization:
`U = B / (C + B)`

V2/V3 borrow APR:
- Nếu `U <= Uopt`: `Rbase + (U/Uopt)*Slope1 - gamma*S`
- Nếu `U > Uopt`: `Rbase + Slope1 + ((U-Uopt)/(1-Uopt))*Slope2 - gamma*S`

Với `gamma = 0.0005` theo đơn vị APR/điểm, tức 0,05 điểm phần trăm mỗi điểm uy tín. APR sàn 1%.

Supply APR:
`borrowAPR_avg * U * (1 - reserveFactor)`

CR:
`CRmax * (1 - S/100)`, với CRmax = 50%.

## Hạn chế nghiên cứu và an toàn

- Token VNĐ trong repo chỉ là mock token, không phải stablecoin được bảo chứng hoặc có khả năng quy đổi VNĐ.
- Hợp đồng đơn giản hóa quản trị lender shares: tiền gửi được ghi nhận theo số dư có thể rút, không phát hành receipt token.
- Lãi tính theo thời gian tuyến tính trên gốc; không cộng lãi kép.
- Không có KYC, AML, oracle thu nhập, chấm điểm tín dụng ngoài chuỗi, dispute resolution, bảo vệ người vay hoặc cơ chế pháp lý. Không dùng nguyên mẫu để huy động vốn/cho vay thật.
- Lãi suất tín dụng đen 180–360%/năm trong biểu đồ là dải giả định so sánh theo đề bài, không phải mức thống kê đại diện cho mọi khoản vay tại Việt Nam.
