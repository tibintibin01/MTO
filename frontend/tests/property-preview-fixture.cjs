// Artificial data only. Never use this fixture to publish a municipal snapshot.
const {createHmac}=require('node:crypto');
const SECRET='synthetic-landing-preview-not-production';
const hash=value=>createHmac('sha256',SECRET).update(value.trim().toUpperCase()).digest('hex');
function snapshot(){
  const years=[
    {tax_year:2023,assessed_value:29290,basic:292.9,sef:292.9,penalty:421.78,discount:0,total_due:1007.58,amount_paid:1107.58,credit:100,balance:0},
    {tax_year:2024,assessed_value:29290,basic:292.9,sef:292.9,penalty:398.34,discount:0,total_due:984.14,amount_paid:0,credit:0,balance:984.14},
    {tax_year:2025,assessed_value:29290,basic:292.9,sef:292.9,penalty:257.75,discount:0,total_due:843.55,amount_paid:0,credit:0,balance:843.55},
    {tax_year:2026,assessed_value:29290,basic:292.9,sef:292.9,penalty:117.16,discount:0,total_due:702.96,amount_paid:0,credit:0,balance:702.96},
  ];
  const a={td_number:'06-0001-00001',td_lookup_hash:hash('06-0001-00001'),pin_lookup_hash:hash('DEMO-A'),
    pin_masked:'DEMO-****',public_account_key:'a'.repeat(64),owner_name:'DEMO OWNER A',barangay:'DEMO BARANGAY',
    location:'DEMO BARANGAY',kind:'RESIDENTIAL LOT',assessed_value:29290,assessment_as_of_year:2026,
    future_assessment:{assessed_value:34000,effective_year:2027},status:'DELINQUENT',balance:2530.65,
    total_credit:100,total_due:3538.23,total_paid:1107.58,billing_breakdown:years,
    last_payment:{period:'2023',date_paid:'2026-10-01'},payment_history:[
      {period:'2023',or_number:'DEMO-001',date_paid:'2026-10-01',amount:1107.58}]};
  const b={...a,pin_lookup_hash:hash('DEMO-B'),public_account_key:'b'.repeat(64),owner_name:'DEMO OWNER B',
    location:'SECOND DEMO LOCATION',future_assessment:null,status:'UPDATED',balance:0,total_credit:0,
    assessed_value:100000,total_due:1800,total_paid:1800,billing_breakdown:[
      {tax_year:2026,assessed_value:100000,basic:1000,sef:1000,penalty:0,discount:200,total_due:1800,amount_paid:1800,credit:0,balance:0}],
    last_payment:{period:'2026',date_paid:'2026-03-01'},payment_history:[
      {period:'2026',or_number:'DEMO-003',date_paid:'2026-03-01',amount:1300},
      {period:'2026',or_number:'DEMO-002',date_paid:'2026-02-01',amount:500}]};
  const pending={...b,td_number:'06-0001-00003',td_lookup_hash:hash('06-0001-00003'),pin_lookup_hash:hash('DEMO-PENDING'),
    public_account_key:'c'.repeat(64),owner_name:'DEMO UNBILLED OWNER',status:'PENDING',balance:0,total_due:0,total_paid:0,
    billing_breakdown:[],payment_history:[],last_payment:null};
  return {schema_version:2,owner_lookup_version:2,published_at:new Date().toISOString(),record_count:3,
    checksum:'d'.repeat(64),properties:[a,b,pending],owner_lookup_index:{[hash('DEMO').slice(0,24)]:[0,1,2]}};
}
module.exports={SECRET,snapshot};
