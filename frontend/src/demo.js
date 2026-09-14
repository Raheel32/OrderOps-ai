// getRandomValues also works on local HTTP preview origins.
export function uid(){ const bytes=crypto.getRandomValues(new Uint8Array(16)); return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join(''); }
export const catalog = [
{id:1,name:'Tapal Danedar Tea 450g',brand:'Tapal',substitution_group:'tea-450',price_paisa:100000,stock:0},
{id:2,name:'Vital Tea 450g',brand:'Vital',substitution_group:'tea-450',price_paisa:98000,stock:20},
{id:3,name:'Dalda Cooking Oil 1L',brand:'Dalda',substitution_group:'oil-1',price_paisa:60000,stock:18},
{id:4,name:'Mezan Cooking Oil 1L',brand:'Mezan',substitution_group:'oil-1',price_paisa:59000,stock:0},
{id:5,name:'Basmati Rice 1kg',brand:'Pantry',substitution_group:'rice-1',price_paisa:35000,stock:0},
{id:6,name:'Shan Biryani Masala 50g',brand:'Shan',substitution_group:'biryani-50',price_paisa:15000,stock:24},
{id:7,name:'National Biryani Masala 50g',brand:'National',substitution_group:'biryani-50',price_paisa:14500,stock:0},
{id:8,name:'Shangrila Tomato Ketchup 500g',brand:'Shangrila',substitution_group:'ketchup-500',price_paisa:32000,stock:15},
{id:9,name:'Young’s Mayonnaise 500ml',brand:'Young’s',substitution_group:'mayo-500',price_paisa:45000,stock:12},
{id:10,name:'Wheat Flour 5kg',brand:'Pantry',substitution_group:'flour-5',price_paisa:65000,stock:22},
];
export const money = n => 'Rs. '+(n/100).toLocaleString('en-PK',{maximumFractionDigits:2});
export const statusLabels={received:'queued',processing:'processing',ready_for_fulfillment:'ready to fulfill',refund_pending:'refund pending',cancelled_cod:'cancelled · COD',awaiting_customer:'awaiting customer',manual_review:'manual review'};
const names=['Ali','Hassan','Sara','Bilal','Ayesha','Zain','Hina','Omar','Maham','Danish'];
export function initialDemo(){
 const products=catalog.map(x=>({...x}));
 const orders=Array.from({length:25},(_,i)=>{
  const id='demo-'+(i+1),status=[6,11,16].includes(i)?'awaiting_customer':i===4?'manual_review':[3,10].includes(i)?'refund_pending':'ready_for_fulfillment';
  const p=products.find(p=>p.id===(status==='awaiting_customer'?1:[3,6,8,9,10][i%5]));
  const quantity=i%3+1,total=p.price_paisa*quantity;
  const o={id,display_id:'#'+(i+1),customer_email:names[i%10].toLowerCase()+'@example.test',risk_score:i===4?.92:.1,payment_method:'prepaid',status,created_at:new Date(Date.now()-(25-i)*23000).toISOString(),original_total_paisa:total,final_total_paisa:total,recovered:false,had_shortage:status==='awaiting_customer'||status==='refund_pending',items:[{product_id:p.id,original_product_id:p.id,quantity,unit_price_paisa:p.price_paisa,name:p.name,reserved:false}],offers:[]};
  if(status==='awaiting_customer'){products.find(p=>p.id===2).stock-=quantity;o.offers=[{id:'offer-'+id,product_id:2,name:'Vital Tea 450g',quantity,unit_price_paisa:93100,status:'pending',held:true}];}
  if(status==='ready_for_fulfillment'&&[1,8,14,19].includes(i)){o.had_shortage=true;o.recovered=true;o.original_total_paisa=100000*quantity;o.final_total_paisa=93100*quantity;o.items=[{product_id:2,original_product_id:1,name:'Vital Tea 450g',quantity,unit_price_paisa:93100,reserved:false}];}
  return o;
 });
 const events=orders.filter(o=>o.status==='awaiting_customer').map(o=>({id:'e-'+o.id,kind:'offer_email',order_id:o.id,created_at:o.created_at,payload:{text:`${o.display_id} · Tapal Danedar Tea 450g is unavailable. Offer: Vital Tea 450g at ${money(93100)} per pack (5% off). Waiting for customer approval.`}}));
 events.unshift({id:'e-refund',kind:'refund_request',created_at:new Date().toISOString(),payload:{text:'#11 · Prepaid order cancelled. Refund request recorded; payment confirmation is pending.'}});
 return {products,orders,events};
}
export function metricsFor(orders){return {orders:orders.length,ready:orders.filter(o=>o.status==='ready_for_fulfillment').length,refunds:orders.filter(o=>o.status==='refund_pending').length,recovered_value_paisa:orders.filter(o=>o.recovered).reduce((s,o)=>s+o.final_total_paisa,0)};}
export function transition(data,action){
 const s=structuredClone(data),o=s.orders.find(x=>x.id===action.id);if(!o)return s;
 const log=(kind,text)=>s.events.unshift({id:uid(),order_id:o.id,kind,payload:{text},created_at:new Date().toISOString()});
 const release=()=>{for(const i of o.items)if(i.reserved){s.products.find(p=>p.id===i.product_id).stock+=i.quantity;i.reserved=false;}for(const a of o.offers)if(a.held){s.products.find(p=>p.id===a.product_id).stock+=a.quantity;a.held=false;a.status='rejected';}};
 const cancel=()=>{release();o.status=o.payment_method==='prepaid'?'refund_pending':'cancelled_cod';log(o.payment_method==='prepaid'?'refund_request':'cancel_cod',`${o.display_id} · Order cancelled. ${o.payment_method==='prepaid'?money(o.original_total_paisa)+' refund request recorded; confirmation pending.':'COD order: no refund required.'}`);};
 const fulfill=()=>{o.status='ready_for_fulfillment';o.recovered=o.had_shortage;o.final_total_paisa=o.items.reduce((n,i)=>n+i.unit_price_paisa*i.quantity,0);log('fulfillment',`${o.display_id} · Stock reserved. ${money(o.final_total_paisa)} grocery order ready for fulfillment.`);if(o.payment_method==='prepaid'&&o.final_total_paisa<o.original_total_paisa)log('partial_refund_request',`${o.display_id} · Price difference ${money(o.original_total_paisa-o.final_total_paisa)} queued for refund.`);};
 const inventory=()=>{const i=o.items[0],p=s.products.find(p=>p.id===i.product_id);if(p.stock>=i.quantity){p.stock-=i.quantity;i.reserved=true;fulfill();return;}o.had_shortage=true;const a=s.products.filter(q=>q.id!==p.id&&q.substitution_group===p.substitution_group&&q.stock>=i.quantity&&(q.price_paisa-Math.floor(q.price_paisa*.05))<=i.unit_price_paisa).sort((a,b)=>a.price_paisa-b.price_paisa)[0];if(!a){log('inventory',`${o.display_id} · No compatible replacement in stock.`);cancel();return;}const price=a.price_paisa-Math.floor(a.price_paisa*.05);a.stock-=i.quantity;o.status='awaiting_customer';o.offers=[{id:uid(),product_id:a.id,name:a.name,quantity:i.quantity,unit_price_paisa:price,status:'pending',held:true}];log('offer_email',`${o.display_id} · ${p.name} unavailable. Offer ${a.name}: ${money(price)} each, 5% off. Stock held; waiting for customer approval.`);};
 if(action.type==='process'&&o.status==='processing'){if(o.risk_score>=.8){o.status='manual_review';log('audit',`${o.display_id} · Risk ${o.risk_score.toFixed(2)}. Paused for a human auditor.`);}else inventory();}
 if(action.type==='approve'&&o.status==='manual_review'){log('audit',`${o.display_id} · Auditor approved the order.`);inventory();}
 if(action.type==='reject'&&['manual_review','awaiting_customer'].includes(o.status))cancel();
 if(action.type==='accept'&&o.status==='awaiting_customer'){const a=o.offers.find(x=>x.status==='pending');if(!a)return s;o.items[0]={...o.items[0],product_id:a.product_id,name:a.name,unit_price_paisa:a.unit_price_paisa,reserved:true};a.held=false;a.status='accepted';log('approval',`${o.display_id} · Customer accepted ${a.name}.`);fulfill();}
 return s;
}
