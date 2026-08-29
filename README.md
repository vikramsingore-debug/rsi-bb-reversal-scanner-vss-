# F&O RSI/Bollinger Band Reversal Scanner (Daily, Telegram Alert)

## Ye Scanner Kya Karta Hai

Har trading day EOD (market close ke baad) automatically chalta hai aur in **saari conditions** ek sath match karne wale F&O stocks Telegram pe bhejta hai:

1. **F&O Universe** — sirf NSE F&O eligible stocks scan hote hain
2. **Volume Rising** — pichle kam se kam 3 sessions se volume continuously badh raha ho
3. **Delivery % > 75%** — latest session ka delivery volume 75% se upar
4. **Prev Session Oversold** — kal RSI(14) < 40 tha AND close, lower Bollinger Band (20, 1.5 std-dev) ke niche tha
5. **Today Reversed** — aaj RSI(14) >= 40 AND close, lower Bollinger Band ke upar/barabar hai

Matlab: stock kal oversold tha (RSI + BB dono se confirm), aur aaj wapas upar reverse ho raha hai — volume aur delivery% se confirm karte hue ki ye genuine institutional buying hai, chart pattern nahi sirf.

## Setup (agar pehle wala scanner already setup kiya hai, to Telegram bot/token reuse ho sakta hai)

### Step 1: GitHub Repo
Naya private repo banao (ya same repo me alag folder), is folder ke saare files (`scanner.py`, `.github/workflows/scanner.yml`, `README.md`) upload karo.

### Step 2: Telegram Secrets (agar pehle se nahi hai)
Agar pichle wale multibagger scanner ke liye already Telegram bot bana chuke ho, wahi `TELEGRAM_BOT_TOKEN` aur `TELEGRAM_CHAT_ID` yahan bhi use kar sakte ho — naya bot banane ki zaroorat nahi.

Repo → **Settings → Secrets and variables → Actions** → add karo:
| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather se mila token |
| `TELEGRAM_CHAT_ID` | apna chat id |

### Step 3: Test Run
Actions tab → "RSI-BB Reversal Scanner" workflow → **Run workflow** button → 2-4 min me complete hoga (F&O universe bada hai isliye pehle wale se thoda zyada time lagega). Telegram pe result check karo.

## Schedule
Default: **Mon-Fri, 18:30 IST** (bhavcopy publish hone ke baad). `.github/workflows/scanner.yml` me cron line change kar sakte ho agar bhavcopy late aata hai ya time shift karna hai.

## Important Cautions (Padhna Zaroori)

1. **F&O universe list**: Script pehle NSE se live list fetch karne ki koshish karta hai; NSE ka site bot-detection karta hai aur kabhi-kabhi fetch fail ho sakta hai — us case me script ek static fallback list use karta hai jo `scanner.py` ke top me `STATIC_FNO_FALLBACK` variable me hai. Ye list **periodically manually verify/update karni padegi** (NSE F&O list quarterly revise hoti hai) — outdated list se naye/removed F&O stocks miss ho sakte hain.

2. **Delivery % data**: NSE ke official daily bhavcopy (`sec_bhavdata_full`) se aata hai. Ye bhi NSE ka hi endpoint hai — agar NSE apna file-naming ya anti-bot protection change kare, ye fetch fail ho sakta hai. Fail hone pe log me clearly dikhega, aur us din delivery% filter ke bina stocks qualify nahi honge (safe default — false signal nahi bhejega, bas signal miss ho sakta hai).

3. **Volume source mismatch**: Volume trend Yahoo Finance se aata hai (NSE bhavcopy se nahi) — dono me minor difference ho sakta hai (Yahoo kabhi-kabhi combined NSE+BSE volume deta hai). Agar tumhe NSE-only volume chahiye exact match ke liye, bata dena, bhavcopy se hi volume bhi le sakte hain (thoda slower hoga, kyunki phir teen sessions ka bhavcopy fetch karna padega).

4. **RSI/BB period assumption**: RSI(14) standard Wilder's method, Bollinger Band(20, 1.5 std-dev) standard SMA-based — agar tumhara conviction alag period pe hai (jaise RSI(9) ya BB(10)), bata dena, easily configurable hai `scanner.py` ke top ke CONFIG section me.

5. Ye ek **mean-reversion/reversal signal** hai, trend-following nahi — false signals aa sakte hain especially choppy/sideways market me. Position sizing aur stop-loss discipline zaroor rakhna.

## Results Kahan Milenge
- **Telegram**: har run ke baad summary (qualifying stocks, unke RSI/BB/delivery% values)
- **CSV artifact**: Actions tab → specific run → Artifacts section me `reversal-signals.zip` (full detail, agar signals mile ho)

## Customize
`scanner.py` ke top CONFIG section me ye sab edit ho sakta hai:
- `RSI_THRESHOLD` (default 40)
- `BB_PERIOD` / `BB_STD_MULT` (default 20, 1.5)
- `VOLUME_LOOKBACK_SESSIONS` (default 3)
- `DELIVERY_PCT_THRESHOLD` (default 75.0)
- `STATIC_FNO_FALLBACK` — apni watchlist ke hisaab se list update kar sakte ho
