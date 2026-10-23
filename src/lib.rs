mod normalize;
mod state;

use std::{collections::HashMap, sync::Arc, time::Duration};
use fqapi_core::{config::Config, device::DevicePool, endpoints::{Ctx, Params, Server}, filter::FilterManager, sign::Manager, upstream::UpstreamClient};
use once_cell::sync::Lazy;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use tokio::sync::Mutex;

static CORE: Lazy<Mutex<Option<Core>>> = Lazy::new(|| Mutex::new(None));
struct Core { server: Server, remote: state::Remote, known: Vec<String> }

pub fn authorized(header: Option<&str>) -> bool {
    let expected = std::env::var("FQ_API_TOKEN").unwrap_or_default();
    expected.len() >= 32 && bool::from(Sha256::digest(header.unwrap_or("").as_bytes())
        .ct_eq(&Sha256::digest(format!("Bearer {expected}").as_bytes())))
}

async fn initialize() -> Result<Core, &'static str> {
    let _ = rustls::crypto::ring::default_provider().install_default();
    let remote = state::Remote::new()?;
    let snapshot = remote.load().await?;
    let known = state::ids(&snapshot);
    tokio::fs::create_dir_all("/tmp/silune-fq").await.map_err(|_| "state_initialization_failed")?;
    tokio::fs::write(state::POOL, snapshot.to_string()).await.map_err(|_| "state_initialization_failed")?;
    let pool = DevicePool::new(state::POOL).await.map_err(|_| "device_pool_initialization_failed")?;
    let up = Arc::new(UpstreamClient::new(pool.clone(), Manager::new()).map_err(|_| "upstream_initialization_failed")?);
    let ctx = Arc::new(Ctx { up, pool, cfg: Arc::new(Config::default()), src_dir: String::new(), filters: Arc::new(FilterManager::default()) });
    Ok(Core { server: Server::new(ctx), remote, known })
}

async fn call(core: &Core, api: &str, params: Params) -> Result<Value, &'static str> {
    let handler = core.server.handler(api).ok_or("unsupported_operation")?;
    let value = handler(&core.server.ctx, &params).await.map_err(|_| "upstream_request_failed")?;
    if value.get("success") == Some(&Value::Bool(false)) || value.get("code").is_some_and(|c| c != 0 && c != 200) {
        return Err("upstream_response_failed");
    }
    Ok(value.get("data").cloned().unwrap_or(value))
}

fn params(pairs: &[(&str, &str)]) -> Params {
    Params::from_pairs(pairs.iter().map(|(k,v)| (k.to_string(),v.to_string())).collect())
}

async fn catalog(core: &Core, id: &str) -> Result<Value, &'static str> {
    let raw = call(core, "directory", params(&[("book_id", id)])).await?;
    normalize::catalog(&raw)
}

fn bounded(q: &HashMap<String,String>, key: &str, default: usize, min: usize, max: usize) -> Result<usize, &'static str> {
    let n = match q.get(key) { Some(s) => s.parse::<usize>().map_err(|_| "invalid_parameters")?, None => default };
    if n < min || n > max { Err("invalid_parameters") } else { Ok(n) }
}

async fn operation(core: &Core, path: &str, q: &HashMap<String,String>) -> Result<(u16, Value), &'static str> {
    if path == "/health" { return Ok((200,json!({"status":"ok","engine":"fqapp-rust","devices":core.server.ctx.pool.count().await}))); }
    if path == "/search" {
        let key = q.get("key").map(|s|s.trim()).filter(|s|!s.is_empty() && s.chars().count()<=200).ok_or("invalid_parameters")?;
        let page = bounded(q,"page",1,1,1000)?;
        let size = bounded(q,"size",10,1,50)?;
        let offset = ((page-1)*size).to_string();
        let raw = call(core,"search",params(&[("query",key),("offset",&offset),("count",&size.to_string()),("tab_type","3")])).await?;
        return Ok((200,normalize::search(&raw,size)));
    }
    let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
    let id = parts.get(1).copied().filter(|id|normalize::valid_id(id)).ok_or("not_found")?;
    match (parts[0],parts.len()) {
        ("book",2) => {
            let detail = call(core,"book_detail_legacy",params(&[("book_id",id)])).await;
            let book = detail.as_ref().ok().and_then(|v|normalize::book(v,Some(id)));
            let book = match book {
                Some(v) => v,
                None => { let raw=call(core,"directory",params(&[("book_id",id)])).await?;normalize::book(&raw,Some(id)).ok_or("book_metadata_missing")? }
            };
            Ok((200,book))
        }
        ("toc",2) => Ok((200,catalog(core,id).await?)),
        ("chapter",3) => {
            let chapter_id=parts[2];
            if !normalize::valid_id(chapter_id) { return Err("invalid_parameters"); }
            let directory=catalog(core,id).await?;
            let entry=directory["item_data_list"].as_array().unwrap().iter().find(|v|v["item_id"]==chapter_id).ok_or("chapter_not_found")?;
            let raw=fqapi_core::endpoints::full::get_chapters(&core.server.ctx,id,&[chapter_id.to_string()]).await.map_err(|_|"upstream_request_failed")?;
            let chapter=normalize::chapter(&raw,id,chapter_id,entry["title"].as_str().unwrap_or(""))?;
            Ok((200,chapter))
        }
        ("batch",2) => {
            let offset=bounded(q,"offset",0,0,999999)?;
            let limit=bounded(q,"limit",20,1,30)?;
            let directory=catalog(core,id).await?;
            let entries=directory["item_data_list"].as_array().unwrap();
            if offset>=entries.len() {return Err("invalid_parameters");}
            let selected=&entries[offset..(offset+limit).min(entries.len())];
            let ids:Vec<_>=selected.iter().map(|v|v["item_id"].as_str().unwrap().to_string()).collect();
            let raw=fqapi_core::endpoints::full::get_chapters(&core.server.ctx,id,&ids).await.map_err(|_|"upstream_request_failed")?;
            let mut chapters=Vec::new();let mut failed=Vec::new();
            for entry in selected {
                let cid=entry["item_id"].as_str().unwrap();
                match normalize::chapter(&raw,id,cid,entry["title"].as_str().unwrap_or("")) {
                    Ok(ch)=>chapters.push(ch), Err(_)=>failed.push(cid)
                }
            }
            let status=if failed.is_empty(){200}else{502};
            Ok((status,json!({"book_id":id,"total":entries.len(),"offset":offset,"limit":selected.len(),"chapters":chapters,"failed":failed})))
        }
        _=>Err("not_found")
    }
}

pub async fn handle(path: &str, query: &str) -> (u16, Value) {
    let path=path.strip_prefix("/api").unwrap_or(path);
    // Public input cannot reach account, device, video, or arbitrary upstream routes.
    if !regex::Regex::new(r"^/(health|search|book/[0-9]{1,24}|toc/[0-9]{1,24}|chapter/[0-9]{1,24}/[0-9]{1,24}|batch/[0-9]{1,24})$").unwrap().is_match(path) {
        return failure("not_found");
    }
    let q:HashMap<String,String>=url::form_urlencoded::parse(query.as_bytes()).into_owned().collect();
    let result=tokio::time::timeout(Duration::from_secs(75),async {
        let mut slot=CORE.lock().await;
        if slot.is_none(){ *slot=Some(initialize().await?); }
        let core=slot.as_mut().unwrap();
        let result=operation(core,path,&q).await;
        // Save new/replaced devices even when the upstream operation failed.
        let persisted=core.remote.save(&core.known).await;
        match persisted {Ok(ids)=>core.known=ids,Err(err)=>return Err(err)}
        result
    }).await;
    match result {
        Ok(Ok((status,data)))=> (status,json!({"code":if status==200{json!(0)}else{json!("PARTIAL_BATCH")},"data":data})),
        Ok(Err(reason))=>failure(reason),
        Err(_)=>failure("upstream_timeout")
    }
}

fn failure(reason: &str)->(u16,Value){
    let status=match reason{"not_found"|"chapter_not_found"=>404,"invalid_parameters"=>400,_=>503};
    (status,json!({"code":"REQUEST_FAILED","message":reason,"data":null}))
}
