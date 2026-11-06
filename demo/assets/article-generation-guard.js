/* Article generation safeguards: scope, price preview and explicit consent.
 * Client-side estimates are illustrative; backend remains authoritative.
 */
(function (global) {
  "use strict";
  const nonNegative = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v)) && Number(v) >= 0;
  const eligible = (card) => card && !card.imageUrl && card.status !== "generating";
  function pendingCards(cards) {
    return (Array.isArray(cards) ? cards : []).filter(eligible);
  }
  function quote(count, {demo = false, free = null, unitPrice = null, balance = null} = {}) {
    const quantity = Number(count);
    if (!Number.isInteger(quantity) || quantity <= 0) return {ok:false, reason:"没有需要生成的配图"};
    if (demo) return {ok:true, demo:true, count:quantity, freeUsed:0, paidCount:0, total:0, balance:null};
    if (!nonNegative(free) || !nonNegative(unitPrice) || !nonNegative(balance)) {
      return {ok:false, reason:"暂时无法取得完整额度和价格信息，请刷新后重试；没有发起扣费请求"};
    }
    const freeUsed = Math.min(quantity, Math.floor(Number(free)));
    const paidCount = quantity - freeUsed;
    const total = paidCount * Number(unitPrice);
    return {ok: true, demo:false, count:quantity, freeUsed, paidCount, unitPrice:Number(unitPrice),
      total, balance:Number(balance), affordable:total <= Number(balance)};
  }
  let dialogOpen = false;
  function confirmGeneration(amount, options = {}) {
    const price = quote(amount, options);
    if (!price.ok) return Promise.resolve({approved:false, quote:price});
    if (typeof document === "undefined" || !document.body || !document.createElement || dialogOpen) {
      return Promise.resolve({approved:false, quote:price});
    }
    dialogOpen = true;
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "hw-article-charge-overlay";
      const isReplacing = Boolean(options.replacing);
      const title = isReplacing ? "确认重新生成这张配图" : "确认生成文章配图";
      const skip = Number(options.skipped || 0);
      overlay.innerHTML = `
        <section class="hw-article-charge-dialog" role="dialog" aria-modal="true" aria-labelledby="hw-article-charge-title">
          <div class="hw-article-charge-kicker">HANDRAW · 本次生成确认</div>
          <h2 id="hw-article-charge-title">${title}</h2>
          <p class="hw-article-charge-help">${isReplacing ? "旧图会保留到新图生成成功；新生成也会单独计费。" : "本次只提交尚未生成的配图，不会重做已经完成的图片。"}</p>
          <div class="hw-article-charge-rows">
            <div><span>本次实际提交</span><strong>${price.count} 张</strong></div>
            ${skip ? `<div><span>已完成并跳过</span><strong>${skip} 张</strong></div>` : ""}
            ${price.demo ? '<div><span>演示模式</span><strong>不消耗真实额度</strong></div>' :
              `<div><span>免费额度使用</span><strong>${price.freeUsed} 张</strong></div>
               <div><span>积分生图</span><strong>${price.paidCount} 张 × ${price.unitPrice} 积分</strong></div>
               <div class="hw-article-charge-total"><span>预计积分消耗</span><strong>${price.total} 积分</strong></div>
               <div><span>当前积分余额</span><strong>${price.balance} 积分</strong></div>`}
          </div>
          ${price.demo ? "" : '<p class="hw-article-charge-note">以上按当前额度估算，后台将在每张图实际提交时核验余额、预留额度，并处理失败退费。</p>'}
          ${!price.demo && !price.affordable ? '<p class="hw-article-charge-error" role="alert">当前余额不足，无法提交这一批配图。请先减少数量或补充额度。</p>' : ""}
          <div class="hw-article-charge-actions">
            <button type="button" data-article-charge-cancel>返回修改</button>
            <button type="button" class="hw-article-charge-primary" data-article-charge-submit
              ${!price.demo && !price.affordable ? "disabled" : ""}>确认生成 ${price.count} 张</button>
          </div>
        </section>`;
      const previousFocus = document.activeElement;
      let settled = false;
      const finish = (approved) => {
        if (settled) return;
        settled = true;
        dialogOpen = false;
        document.removeEventListener("keydown", onKeyDown, true);
        overlay.remove();
        if (previousFocus?.isConnected && typeof previousFocus.focus === "function") previousFocus.focus();
        resolve({approved, quote:price});
      };
      const onKeyDown = (e) => {
        if (e.key === "Escape") { e.preventDefault(); finish(false); return; }
        if (e.key !== "Tab") return;
        const focusable = [...overlay.querySelectorAll("button:not(:disabled)")];
        if (!focusable.length) return;
        if (e.shiftKey && document.activeElement === focusable[0]) {
          e.preventDefault(); focusable[focusable.length - 1].focus();
        } else if (!e.shiftKey && document.activeElement === focusable[focusable.length - 1]) {
          e.preventDefault(); focusable[0].focus();
        }
      };
      overlay.addEventListener("click", (e) => { if (e.target === overlay) finish(false); });
      overlay.querySelector("[data-article-charge-cancel]").addEventListener("click", () => finish(false));
      overlay.querySelector("[data-article-charge-submit]").addEventListener("click", () => finish(true));
      document.addEventListener("keydown", onKeyDown, true);
      document.body.appendChild(overlay);
      overlay.querySelector("[data-article-charge-cancel]").focus();
    });
  }
  global.HandrawArticleGenerationGuard = {pendingCards, quote, confirmGeneration};
})(window);
