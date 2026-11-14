(function () {
  'use strict';
  const id = new URLSearchParams(location.search).get('orderId');
  const status = document.getElementById('checkout-status');
  const button = document.getElementById('checkout-sync');
  const image = document.getElementById('checkout-qr');
  const open = document.getElementById('checkout-open');
  let timer;
  async function request(path, method = 'GET') {
    const response = await fetch(path, {method, credentials:'include', ...(method === 'POST' ? {headers:{'Content-Type':'application/json'}, body:'{}'} : {})});
    const body = await response.json();
    if (!response.ok) throw Error(body.error || '暂时无法核验支付结果，请稍后重试');
    return body;
  }
  async function render() {
    const result = await request('/api/billing/orders/' + encodeURIComponent(id));
    const order = result.order;
    document.getElementById('checkout-purpose').textContent = order.purpose === 'cash' ? '生图余额充值' : '购买社区积分';
    document.getElementById('checkout-amount').textContent = '¥' + (order.amountCents / 100).toFixed(2);
    const paid = ['paid','partially_refunded','refunded'].includes(order.status);
    status.textContent = paid ? '支付已核验到账，可前往订单记录或返回钱包查看。' : order.status === 'pending' ? (result.qr ? '扫码付款，或在手机上打开付款链接。' : '订单正在核验，请勿重复下单。可点击核验到账查询现有订单。') : '订单已结束，请前往订单记录查看状态，或返回钱包重新购买。';
    image.hidden = paid || !result.qrImageUrl;
    if (!image.hidden) window.HandrawImages.set(image, result.qrImageUrl, {width:256});
    open.hidden = paid || !result.paymentLink;
    if (!open.hidden) open.href = result.paymentLink;
    button.disabled = order.status !== 'pending';
    return order.status === 'pending';
  }
  async function sync() {
    clearTimeout(timer); button.disabled = true;
    try {
      await request('/api/billing/orders/' + encodeURIComponent(id) + '/sync', 'POST');
      if (await render()) timer = setTimeout(sync, 5000);
    } catch (error) {status.textContent = error.message; button.disabled = false;}
  }
  button.onclick = sync;
  window.addEventListener('pagehide', () => clearTimeout(timer), {once:true});
  if (!id) {status.textContent = '缺少订单编号，请从钱包进入付款。'; button.disabled = true; return;}
  render().then(pending => {if (pending) timer = setTimeout(sync, 5000);}).catch(error => {status.textContent = error.message;button.disabled = true;});
})();
