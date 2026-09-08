import { useEffect, useRef, useState } from "react";

import "./DemoGuide.css";

// Deliberately independent of ResearchReport and all promotion/eligibility code.
// These are normalized, linear terminal-payoff examples, not exchange contracts.
const examples = [
  {
    name: "牛市看跌价差",
    english: "Bull put spread",
    outlook: "理解下跌的边界",
    description: "卖出 90 看跌，买入 80 看跌。到期价格不低于 90 时，获得示例中的最大到期收益。",
    credit: 2,
    maxLoss: 8,
    breakeven: "88",
    legs: ["卖出看跌 · 90", "买入看跌 · 80"],
    lesson: "买入的 80 看跌腿把下跌一侧的到期损失封顶；最大亏损仍是最大收益的 4 倍。",
    payoff: (price: number) => 2 - Math.max(90 - price, 0) + Math.max(80 - price, 0),
  },
  {
    name: "熊市看涨价差",
    english: "Bear call spread",
    outlook: "理解上涨的边界",
    description: "卖出 110 看涨，买入 120 看涨。到期价格不高于 110 时，获得示例中的最大到期收益。",
    credit: 2.5,
    maxLoss: 7.5,
    breakeven: "112.5",
    legs: ["卖出看涨 · 110", "买入看涨 · 120"],
    lesson: "价格向上突破后，损失增加，直到保护腿生效；有限风险并不表示一定赚钱。",
    payoff: (price: number) => 2.5 - Math.max(price - 110, 0) + Math.max(price - 120, 0),
  },
  {
    name: "铁鹰双边价差",
    english: "Iron condor",
    outlook: "理解区间的边界",
    description: "组合 80 / 90 看跌价差与 110 / 120 看涨价差。到期价格在 90–110 内时，获得示例中的最大到期收益。",
    credit: 3,
    maxLoss: 7,
    breakeven: "87 / 113",
    legs: ["买入看跌 · 80", "卖出看跌 · 90", "卖出看涨 · 110", "买入看涨 · 120"],
    lesson: "同一到期价格不可能同时落在两侧最外端，因此这个例子的最大到期亏损是 7 点，不是两侧损失相加。",
    payoff: (price: number) => 3 - Math.max(90 - price, 0) + Math.max(80 - price, 0)
      - Math.max(price - 110, 0) + Math.max(price - 120, 0),
  },
] as const;

const steps = ["选择一个结构", "观察风险与收益", "理解证据与限制"];
const signed = (value: number) => `${value < 0 ? "−" : value > 0 ? "+" : ""}${Math.abs(value)} 点`;

function PayoffChart({ index, price }: { index: number; price: number }): React.JSX.Element {
  const example = examples[index];
  const x = (value: number) => 42 + (value - 60) * 6;
  const y = (value: number) => 86 - value * 14;
  const points = Array.from({ length: 81 }, (_, offset) => {
    const at = 60 + offset;
    return `${x(at)},${y(example.payoff(at))}`;
  }).join(" ");
  return (
    <svg className="demo-payoff" viewBox="0 0 560 245" role="img" aria-labelledby="demo-payoff-title demo-payoff-desc">
      <title id="demo-payoff-title">{example.name}的示例到期损益</title>
      <desc id="demo-payoff-desc">横轴为标准化到期价格，纵轴为损益点数。最大收益 {example.credit} 点，最大亏损 {example.maxLoss} 点。当前价格 {price}，损益 {signed(example.payoff(price))}。</desc>
      <rect x="42" y="16" width="480" height="70" className="demo-chart-profit" />
      <rect x="42" y="86" width="480" height="126" className="demo-chart-loss" />
      <line x1="42" x2="522" y1="86" y2="86" className="demo-chart-zero" />
      <text x="8" y="90">0</text>
      <text x="48" y="33">收益</text>
      <text x="48" y="200">亏损</text>
      {[60, 80, 100, 120, 140].map((value) => (
        <text key={value} x={x(value)} y="233" textAnchor="middle">{value}</text>
      ))}
      <polyline points={points} className="demo-chart-line" />
      <line x1={x(price)} x2={x(price)} y1="16" y2="212" className="demo-chart-cursor" />
      <circle cx={x(price)} cy={y(example.payoff(price))} r="5" className="demo-chart-point" />
    </svg>
  );
}

export function DemoGuide(): React.JSX.Element {
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState(0);
  const [price, setPrice] = useState(100);
  const [complete, setComplete] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);
  const example = examples[selected];

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    heading.current?.focus();
  }, [step, complete]);

  return (
    <main className="demo-guide" id="surface-main" data-testid="demo-tour">
      <header className="demo-intro">
        <p className="demo-eyebrow">三分钟 · 无需配置 · 全程离线</p>
        <h1>离线学习导览</h1>
        <p>读懂一个策略，需要看清收益、风险，以及结论背后的证据。</p>
        <div className="demo-teaching-note" role="note">
          <strong>教学示例，不是当前行情</strong>
          <span>以 100 为参考价格，使用示例点数。样例不会进入真实研究报告。</span>
        </div>
      </header>

      <nav className="demo-steps" aria-label="学习步骤">
        {steps.map((label, index) => (
          <button key={label} type="button" aria-current={step === index ? "step" : undefined}
            onClick={() => { setStep(index); setComplete(false); }}>
            <span aria-hidden="true">0{index + 1}</span>{label}
          </button>
        ))}
      </nav>

      <section className="demo-stage" aria-labelledby="demo-step-title">
        <div className="demo-stage-heading">
          <p className="demo-eyebrow">{complete ? "导览完成" : `第 ${step + 1} 步 / 3`}</p>
          <h2 id="demo-step-title" tabIndex={-1} ref={heading}>
            {complete ? "你已完成导览" : steps[step]}
          </h2>
        </div>

        {step === 0 ? (
          <>
            <p className="demo-stage-description">选择一个例子，看看保护腿如何限定到期损失。这三个例子没有优劣排名。</p>
            <div className="demo-examples" aria-label="教学结构">
              {examples.map((item, index) => (
                <button className="demo-example" type="button" key={item.name}
                  aria-pressed={selected === index} onClick={() => { setSelected(index); setPrice(100); }}>
                  <span className="demo-example-number">0{index + 1} <span>{selected === index ? "已选择" : "选择示例"}</span></span>
                  <strong>{item.name}</strong>
                  <span className="demo-example-english">{item.english}</span>
                  <span className="demo-example-outlook">{item.outlook}</span>
                  <span>{item.description}</span>
                </button>
              ))}
            </div>
            <div className="demo-actions">
              <button className="demo-primary" type="button" onClick={() => setStep(1)}>查看风险与收益</button>
              <span>已选：{example.name}</span>
            </div>
          </>
        ) : step === 1 ? (
          <div data-testid="demo-risk-step">
            <p className="demo-stage-description">{example.name} · 拖动到期价格，观察损益。曲线只描述这个线性模型的到期结果。</p>
            <div className="demo-risk-layout">
              <div className="demo-chart-panel">
                <div className="demo-result">
                  <span>参考价格 100 → 到期价格 {price}</span>
                  <output aria-label="示例到期损益" aria-live="polite" data-negative={example.payoff(price) < 0}>
                    {signed(example.payoff(price))}
                  </output>
                </div>
                <PayoffChart index={selected} price={price} />
                <label className="demo-slider-label" htmlFor="demo-expiry-price">示例到期价格 <strong aria-hidden="true">{price}</strong></label>
                <input id="demo-expiry-price" type="range" min="60" max="140" step="1" value={price}
                  onChange={(event) => setPrice(Number(event.target.value))} />
                <p className="demo-chart-caption">也可用方向键调整价格 · 损益单位：示例点</p>
              </div>
              <aside className="demo-economics" aria-label="示例结构与边界">
                <h3>这份收益，伴随着什么风险？</h3>
                <dl>
                  <div><dt>最大到期收益</dt><dd>{example.credit} 点</dd></div>
                  <div><dt>最大到期亏损</dt><dd>{example.maxLoss} 点</dd></div>
                  <div><dt>到期盈亏平衡价格</dt><dd>{example.breakeven}</dd></div>
                </dl>
                <ul aria-label="示例期权腿">{example.legs.map((leg) => <li key={leg}>{leg}</li>)}</ul>
                <p>{example.lesson}</p>
              </aside>
            </div>
            <div className="demo-actions">
              <button className="demo-primary" type="button" onClick={() => setStep(2)}>查看证据与限制</button>
              <button className="demo-secondary" type="button" onClick={() => setStep(0)}>换一个结构</button>
            </div>
          </div>
        ) : (
          <div data-testid="demo-evidence-step">
            <p className="demo-stage-description">{complete ? "你已经能分辨可计算的结构边界与仍需验证的研究结论。接下来可以检查随安装包附带的真实阻断快照。" : "读懂收益曲线，还不能判断这个策略是否值得研究。以下证据各自回答不同的问题。"}</p>
            <div className="demo-evidence-grid">
              <article><span className="demo-evidence-label">结构计算</span><h3>到期边界可以算清</h3><p>这个例子的最大收益是 {example.credit} 点，最大亏损是 {example.maxLoss} 点。它说明可能的到期结果，不说明每种结果发生的概率。</p></article>
              <article><span className="demo-evidence-label">行情与成本</span><h3>实际可成交性仍需核验</h3><p>示例未计费用、滑点和提前平仓，也不对应真实交易所的合约计价或结算规则。真实研究需要新鲜报价、流动性和成本证据。</p></article>
              <article><span className="demo-evidence-label">历史与预测</span><h3>胜率仍然未知</h3><p>真实历史需要相同规则下的独立样本，预测还需要单独校准。样本不足时保留空值；不能用这张曲线补出胜率。</p></article>
            </div>
            <div className="demo-takeaway" role="note"><strong>没有证据时，明确暂停结论。</strong><p>真实快照可能显示“暂无可靠策略”。那表示当前证据没有通过检查，并不是导览中的示例获得了研究资格。</p></div>
            <div className="demo-actions">
              {complete ? <a className="demo-primary" href="./index.html">查看真实快照</a>
                : <button className="demo-primary" type="button" onClick={() => setComplete(true)}>完成导览</button>}
              <button className="demo-secondary" type="button" onClick={() => { setStep(0); setComplete(false); }}>重新选择示例</button>
            </div>
          </div>
        )}
      </section>

      <footer className="demo-guide-footer">
        <span>仅用于学习结构 · 不连接账户，不发送订单</span>
        {!complete ? <a href="./index.html">跳过导览，查看真实快照</a> : null}
      </footer>
    </main>
  );
}
