use serde_json::{json, Value};
use std::time::Duration;

pub const POOL:&str="/tmp/silune-fq/device_pool.json";
pub struct Remote {client:reqwest::Client,url:String,token:String}
pub fn ids(v:&Value)->Vec<String>{v["android"].as_array().map(|a|a.iter().filter_map(|d|d["device_id"].as_str().map(str::to_owned)).collect()).unwrap_or_default()}
impl Remote {
    pub fn new()->Result<Self,&'static str>{
        let url=std::env::var("FQ_STATE_URL").map_err(|_|"state_not_configured")?;
        let parsed=url::Url::parse(&url).map_err(|_|"state_not_configured")?;
        let token=std::env::var("FQ_STATE_TOKEN").map_err(|_|"state_not_configured")?;
        if parsed.scheme()!="https"||token.len()<32{return Err("state_not_configured");}
        let client=reqwest::Client::builder().http1_only().redirect(reqwest::redirect::Policy::none()).timeout(Duration::from_secs(10)).build().map_err(|_|"state_not_configured")?;
        Ok(Self{client,url,token})
    }
    pub async fn load(&self)->Result<Value,&'static str>{
        let r=self.client.get(&self.url).bearer_auth(&self.token).send().await.map_err(|e|{eprintln!("state transport: timeout={} connect={}",e.is_timeout(),e.is_connect());"state_unavailable"})?;
        if !r.status().is_success(){return Err("state_unavailable");}
        let v:Value=r.json().await.map_err(|_|"state_invalid")?;
        if !v["android"].is_array(){return Err("state_invalid");}
        Ok(v)
    }
    pub async fn save(&self,known:&[String])->Result<Vec<String>,&'static str>{
        let Ok(raw)=tokio::fs::read(POOL).await else {return Err("state_snapshot_missing");};
        let snapshot:Value=serde_json::from_slice(&raw).map_err(|_|"state_invalid")?;
        let current=ids(&snapshot);
        let removed:Vec<_>=known.iter().filter(|id|!current.contains(id)).collect();
        let r=self.client.post(&self.url).bearer_auth(&self.token).json(&json!({"pool":snapshot,"removed":removed})).send().await.map_err(|_|"state_persist_failed")?;
        if !r.status().is_success(){return Err("state_persist_failed");}
        Ok(current)
    }
}
