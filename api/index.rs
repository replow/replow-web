use silune_fq_parser::{handle, authorized};
use vercel_runtime::{run, service_fn, Error, Request, Response};

#[tokio::main]
async fn main() -> Result<(), Error> {
    run(service_fn(handler)).await
}

async fn handler(request: Request) -> Result<Response<String>, Error> {
    let (status, payload) = if !authorized(request.headers().get("authorization").and_then(|h| h.to_str().ok())) {
        (401, serde_json::json!({"code":"REQUEST_FAILED","message":"authentication_required","data":null}))
    } else if request.method() != "GET" && request.method() != "HEAD" {
        (405, serde_json::json!({"code":"REQUEST_FAILED","message":"method_not_allowed","data":null}))
    } else {
        handle(request.uri().path(), request.uri().query().unwrap_or("")).await
    };
    let body = if request.method() == "HEAD" { String::new() } else { payload.to_string() };
    Ok(Response::builder().status(status)
        .header("Content-Type", "application/json; charset=utf-8")
        .header("Cache-Control", "private, no-store, max-age=0")
        .header("CDN-Cache-Control", "no-store")
        .header("Vercel-CDN-Cache-Control", "no-store")
        .header("Vary", "Authorization")
        .header("X-Content-Type-Options", "nosniff")
        .body(body)?)
}
