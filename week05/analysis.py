# 5주차 분석: 미국 10년 국채선물(ZN)의 밤사이 변동이 다음 날 10년 국채선물(KTB10) 장중 움직임을 예측하는가
# API 를 부르지 않는다. fetch_data.py 로 받아 둔 results/ 파일만 읽어서 표와 results/analysis_summary.json 을 만든다
#
# 기간 나누기 (2026-11-16 10:2x, 결과를 보기 전에 정함)
#   학습 2022-01-01 ~ 2023-12-31 : 계수 추정
#   검증 2024-01-01 ~ 2024-12-31 : 후보 모형 고르기
#   시험 2025-01-01 ~ 2026-11-13 : 규칙을 확정한 뒤 backtest.py 에서 한 번만 본다. 이 파일은 시험 구간을 쓰지 않는다
#
#   python analysis.py
import json

import numpy as np
import pandas as pd
import statsmodels.api as sm

from fetch_data import RESULTS, load_daily, load_minute

FIT_END, VAL_END, TEST_END = "2024-01-01", "2025-01-01", "2026-11-14"
COST_PT = 0.0171   # KTB10 1계약 왕복 비용(가격 포인트). strategy.py COST_PT 설명 참고
ZN_STALE_MAX = 4   # KTB 날짜보다 ZN 마지막 봉이 4일 넘게 오래되면 ZN 값을 쓰지 않는다 (2022-06~2023-01 봉 누락, week03 7절 5번)


def ktb_expiry_next(idx):
    """KTB 국채선물 최종거래일 = 결제월(3·6·9·12월) 셋째 화요일 [KRX 상품 명세].
    연결 시리즈는 그다음 거래일부터 새 월물이라 그날의 밤사이 갭은 가격 변동이 아니다"""
    out = []
    for y in sorted(set(idx.year)):
        for mth in (3, 6, 9, 12):
            tue = pd.date_range(f"{y}-{mth:02d}-01", periods=21, freq="D")
            third = tue[tue.weekday == 1][2]
            nxt = idx[idx > third]
            if len(nxt):
                out.append(nxt[0])
    return pd.DatetimeIndex(out)


def zn_roll_days(z):
    """ZN 연결 일봉 교체일: 2·5·8·11월 마지막 8영업일 ~ 다음 달 첫 3영업일 중 밤사이 갭이 가장 큰 날 (week03 roll_days 와 같은 방법)"""
    gap = (z.open - z.close.shift()).abs()
    out = []
    for (y, mth), g in z.groupby([z.index.year, z.index.month]):
        if mth in (2, 5, 8, 11) and len(g) > 5:
            win = gap.reindex(list(g.index[-8:]) + list(z.index[z.index > g.index[-1]][:3])).dropna()
            if len(win):
                out.append(win.idxmax())
    return pd.DatetimeIndex(out)


def build():
    """날짜별 표 하나. t 일 KTB10 의 장중 변동(intra)과 그 전에 알 수 있는 값들.
    ZN 날짜 d 의 봉은 한국 시간 d 일 08:00 ~ d+1 일 07:00 (CME 거래일, week03 2절). 그래서 KTB t 일 개장(08:45) 전에
    끝난 ZN 봉 중 가장 최근 것 = t 보다 앞선 마지막 ZN 날짜의 봉이다"""
    k = load_daily("ktb")
    k = k[k.index < TEST_END].copy()
    k["gap"] = k.open - k.close.shift()          # 밤사이 (전일 15:45 종가 → 08:45 시가)
    k["intra"] = k.close - k.open                # 장중 (08:45 시가 → 15:45 종가)
    k["prev_intra"] = k.intra.shift()
    k["ktb_roll"] = k.index.isin(ktb_expiry_next(k.index))

    z = load_daily("zn")
    z = z[z.index >= "2021-06-01"].copy()
    z["zret"] = z.close - z.close.shift()
    z["zn_roll"] = z.index.isin(zn_roll_days(z))
    zz = z[["zret", "zn_roll"]].reset_index().rename(columns={"t": "zt"})
    d = pd.merge_asof(k.reset_index(), zz, left_on="t", right_on="zt", allow_exact_matches=False).set_index("t")
    d["zn_stale"] = (d.index - d.zt).dt.days
    d.loc[(d.zn_stale > ZN_STALE_MAX) | d.zn_roll.astype(bool), "zret"] = np.nan
    d.loc[d.ktb_roll, "gap"] = np.nan
    d["split"] = np.where(d.index < FIT_END, "fit", np.where(d.index < VAL_END, "val", "test"))
    return d.iloc[1:]


def ols(d, y, X, const=True):
    d = d[[y] + X].dropna()
    r = sm.OLS(d[y], sm.add_constant(d[X]) if const else d[X]).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    return {"n": int(r.nobs), "r2": round(float(r.rsquared), 4),
            "coef": {k: round(float(v), 4) for k, v in r.params.items()},
            "t": {k: round(float(v), 2) for k, v in r.tvalues.items()}}


def data_quality(d):
    """연결 일봉 품질: 시가·종가가 고가~저가 밖인 날, 1분봉으로 다시 만든 일봉과의 차이"""
    k = load_daily("ktb")
    bad = ((k.open > k.high) | (k.open < k.low) | (k.close > k.high) | (k.close < k.low))
    m = load_minute("ktb")
    by = m.groupby(m.index.normalize())
    rebuilt = pd.DataFrame({"open": by.open.first(), "high": by.high.max(), "low": by.low.min(), "close": by.close.last()})
    j = rebuilt.join(k[["open", "high", "low", "close"]], rsuffix="_d", how="inner")
    diff = {c: int((j[c] - j[c + "_d"]).abs().gt(1e-9).sum()) for c in ("open", "high", "low", "close")}
    gaps = pd.Series(k.index).diff().dt.days
    return {"ktb_daily_days": len(k), "ktb_daily_range": [str(k.index[0].date()), str(k.index[-1].date())],
            "ohlc_out_of_range_days": int(bad.sum()),
            "max_calendar_gap_days": int(gaps.max()),
            "rebuilt_vs_daily_days": len(j), "rebuilt_vs_daily_mismatch": diff}


def minute_leadlag():
    """장중(09:00~15:30) 1분·5분 수익률의 시차 상관. lag L>0 = L 봉 전 ZN 과 지금 KTB10 (ZN 이 앞섬)"""
    k = load_minute("ktb")
    k = k[k.index.strftime("%H:%M") != "15:45"].close
    z = load_minute("zn").close
    z = z[z.index >= k.index[0].normalize()]
    out = {}
    for f in ("1min", "5min"):
        kr = k.resample(f).last().diff()
        zr = z.resample(f).last().diff()
        kr = kr[(kr.index.hour >= 9) & (kr.index.strftime("%H:%M") <= "15:30")].dropna()
        out[f] = {"n": len(kr), "corr_by_lag": {L: round(float(kr.corr(zr.shift(L).reindex(kr.index))), 3)
                                               for L in range(-3, 4)}}
    out["period"] = [str(k.index[0].date()), str(k.index[-1].date())]
    return out


def compare_models(d):
    """학습(2022~2023)으로 계수를 구하고 검증(2024)에서 예측 부호대로 하루 매매했을 때를 비교. 상수항 없음
    (2022~2024 장중 평균이 + 였지만 금리 방향에 대한 베팅이라 넣지 않는다)"""
    cands = {"A 전일 장중": ["prev_intra"], "B 전일 장중 + ZN": ["prev_intra", "zret"],
             "C 전일 장중 + ZN + 갭": ["prev_intra", "zret", "gap"], "D 갭": ["gap"], "E ZN": ["zret"]}
    fit, val = d[d.split == "fit"], d[d.split == "val"]
    rows = []
    for name, X in cands.items():
        f = fit[["intra"] + X].dropna()
        b = sm.OLS(f.intra, f[X]).fit().params
        v = val[["intra"] + X].dropna()
        p = v[X] @ b
        pnl = np.sign(p) * v.intra - COST_PT
        rows.append({"model": name, "coef": {k: round(float(x), 4) for k, x in b.items()}, "val_n": len(v),
                     "val_corr": round(float(np.corrcoef(p, v.intra)[0, 1]), 3),
                     "val_hit": round(float((np.sign(p) == np.sign(v.intra)).mean()), 3),
                     "val_krw_per_day": round(float(pnl.mean()) * 1e6)})
    return rows


def main():
    d = build()
    tr = d[d.split != "test"]  # 학습 + 검증 (2022~2024)
    out = {"split": {"fit": ["2022-01-01", "2023-12-31"], "val": ["2024-01-01", "2024-12-31"],
                     "test": ["2025-01-01", "2026-11-13"]},
           "n": d.split.value_counts().to_dict(),
           "quality": data_quality(d)}

    # 가설 1: 미국 밤사이 변동이 KTB10 밤사이 갭을 설명한다 (학습+검증)
    out["H1_gap_on_zn"] = ols(tr, "gap", ["zret"])
    beta_gap = out["H1_gap_on_zn"]["coef"]["zret"]
    tr = tr.assign(gfit=beta_gap * tr.zret, gres=tr.gap - beta_gap * tr.zret)
    # 가설 2: 개장 후에도 미국 쪽 정보가 남아 장중 움직임을 예측한다
    out["H2_intra_on_zn"] = ols(tr, "intra", ["zret"])
    out["H2_intra_on_gfit_gres"] = ols(tr, "intra", ["gfit", "gres"])
    # 데이터에서 나온 것: 전일 장중 움직임의 반전
    out["H3_intra_on_prev"] = ols(tr, "intra", ["prev_intra"])
    out["H3_by_year"] = {int(y): {"n": len(g), "corr": round(float(g.intra.corr(g.prev_intra)), 3)}
                         for y, g in tr.groupby(tr.index.year)}
    vol = tr.intra.abs().rolling(20).mean().shift()
    hi = vol > vol.median()
    out["H3_by_vol_regime"] = {name: {"n": int(m.sum()), "corr": round(float(tr[m].intra.corr(tr[m].prev_intra)), 3)}
                               for name, m in (("변동성 높음", hi), ("변동성 낮음", ~hi & vol.notna()))}
    out["minute_leadlag"] = minute_leadlag()
    out["models"] = compare_models(d)

    # 채택 모형 A 의 최종 계수: 학습+검증 전체(2022~2024), 상수항 없음
    f = tr[["intra", "prev_intra"]].dropna()
    final = sm.OLS(f.intra, f[["prev_intra"]]).fit()
    out["final_beta"] = round(float(final.params.prev_intra), 4)
    out["final_beta_t"] = round(float(final.tvalues.prev_intra), 2)
    out["intra_abs_median_pt"] = round(float(tr.intra.abs().median()), 4)
    out["range_median_pt"] = round(float((d[d.split != "test"].high - d[d.split != "test"].low).median()), 4)

    (RESULTS / "analysis_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    d.drop(columns=["zt"]).to_csv(RESULTS / "daily_dataset.csv", float_format="%.6g", encoding="utf-8-sig")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
