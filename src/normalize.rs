use std::collections::HashSet;
use once_cell::sync::Lazy;
use regex::Regex;
use serde_json::{json, Value};

static TAGS:Lazy<Regex>=Lazy::new(||Regex::new(r"<[^>]*>").unwrap());
static BREAKS:Lazy<Regex>=Lazy::new(||Regex::new(r"(?i)<(?:br\s*/?|/p|/div)>").unwrap());
pub fn valid_id(s:&str)->bool{!s.is_empty()&&s.len()<=24&&s.bytes().all(|b|b.is_ascii_digit())}
fn string(v:&Value,keys:&[&str])->String{
    keys.iter().filter_map(|k|v.get(k)).find_map(|v|match v{
        Value::String(s) if !s.is_empty()=>Some(s.clone()),Value::Number(n)=>Some(n.to_string()),_=>None
    }).unwrap_or_default()
}
fn text(s:&str)->String{html_escape::decode_html_entities(&TAGS.replace_all(&BREAKS.replace_all(s,"\n"),"")).trim().to_string()}
fn count(v:&Value,keys:&[&str])->usize{string(v,keys).parse().unwrap_or(0)}

pub fn book(v:&Value,fallback:Option<&str>)->Option<Value>{
    if let Some(a)=v.as_array(){return a.iter().find_map(|v|book(v,fallback));}
    if !v.is_object(){return None;}
    let title=text(&string(v,&["book_name","bookName","title","original_book_name"]));
    let id=string(v,&["book_id","bookId"]);
    let id=if id.is_empty(){fallback.unwrap_or("").to_string()}else{id};
    if !title.is_empty()&&valid_id(&id){
        let mut cover=string(v,&["thumb_url","cover_url","coverUrl","cover"]);
        if cover.is_empty(){cover=v.pointer("/cover/url_list/0").and_then(Value::as_str).unwrap_or("").to_string();}
        return Some(json!({"bookId":id,"bookName":title,"author":string(v,&["author","author_name"]),
            "coverUrl":cover,"description":string(v,&["abstract","description","intro"]),
            "totalChapters":count(v,&["serial_count","total_chapter","chapter_count","totalChapters"])}));
    }
    for key in ["book_info","book_data","data"]{if let Some(found)=v.get(key).and_then(|v|book(v,fallback)){return Some(found);}}
    None
}

fn collect_books(v:&Value,out:&mut Vec<Value>,seen:&mut HashSet<String>){
    if v.get("book_id").is_some() || v.get("bookId").is_some() {
      if let Some(found)=book(v,None){
        let id=found["bookId"].as_str().unwrap().to_string();
        if seen.insert(id){out.push(found);}
        // Do not descend through a complete book; recommendations are separate results.
        return;
      }
    }
    match v{Value::Array(a)=>a.iter().for_each(|v|collect_books(v,out,seen)),
        Value::Object(m)=>m.values().for_each(|v|collect_books(v,out,seen)),_=>{}}
}
pub fn search(raw:&Value,size:usize)->Value{
    let mut books=Vec::new();collect_books(raw,&mut books,&mut HashSet::new());
    let explicit=raw.get("has_more").or_else(||raw.get("hasMore"));
    let has_more=explicit.map(|v|v==true||v==1||v=="1").unwrap_or(books.len()>=size);
    books.truncate(size);json!({"books":books,"hasMore":has_more})
}

pub fn catalog(raw:&Value)->Result<Value,&'static str>{
    let list=raw.get("item_data_list").or_else(||raw.get("item_list")).and_then(Value::as_array).ok_or("directory_missing")?;
    let mut seen=HashSet::new();let mut items=Vec::new();
    for entry in list{
        let id=string(entry,&["item_id","itemId","chapter_id","chapterId","id"]);
        if !valid_id(&id)||!seen.insert(id.clone()){return Err("invalid_directory");}
        items.push(json!({"item_id":id,"title":text(&string(entry,&["title","item_title","chapter_name"]))}));
    }
    if items.is_empty(){return Err("directory_empty");}
    Ok(json!({"item_data_list":items,"total":items.len(),"serial_count":items.len(),"book_info":raw.get("book_info")}))
}

pub fn chapter(raw:&Value,book_id:&str,id:&str,title:&str)->Result<Value,&'static str>{
    let infos=raw.pointer("/data/item_infos").ok_or("chapter_missing")?;
    let item=if let Some(a)=infos.as_array(){a.iter().find(|v|string(v,&["item_id","itemId","chapter_id"])==id)}else{infos.get(id)}.ok_or("chapter_missing")?;
    let content=item.get("content").and_then(Value::as_str).ok_or("chapter_missing")?;
    let body=text(content);
    let length=body.chars().count();
    let title=if title.is_empty(){string(item,&["title","item_title"])}else{title.to_string()};
    let front_matter=matches!(title.trim(),"版权信息"|"版权页"|"版权信息页");
    let private=body.chars().filter(|c|('\u{e000}'..='\u{f8ff}').contains(c)).count();
    let words=body.chars().filter(|c|c.is_alphabetic()).count();
    let declared=count(item,&["word_count","wordCount"]);
    let ciphertext=body.len()>80 && body.bytes().all(|b|b.is_ascii_alphanumeric()||b"+/=\r\n".contains(&b)) && !body.contains(' ');
    let placeholder=["章节内容获取失败","本章下载失败","本章节暂无内容","请打开番茄小说APP"].iter().any(|s|body.chars().take(100).collect::<String>().contains(s));
    if length<if front_matter{8}else{80}||(!front_matter&&length==200)||length*4<declared*3||private>3.max(length/100)||words<if front_matter{5}else{20}||ciphertext||placeholder||item.get("isChapterLock")==Some(&Value::Bool(true)){
        return Err("chapter_incomplete_or_unreadable");
    }
    Ok(json!({"bookId":book_id,"chapterId":id,"title":title,"txtContent":body,"wordCount":declared,"isChapterLock":false}))
}

#[cfg(test)]
mod tests{
    use super::*;
    #[test]fn search_keeps_all_nested_results_and_large_string_ids(){
        let data=json!({"data":[{"book_data":[{"book_id":"7000000000000000001","book_name":"<em>甲</em>","author":"A"},{"book_id":"7000000000000000002","book_name":"乙"}]}],"has_more":0});
        assert_eq!(search(&data,10)["books"].as_array().unwrap().len(),2);
        assert_eq!(search(&data,10)["books"][0]["bookName"],"甲");
    }
    #[test]fn catalog_rejects_duplicate_or_missing_ids(){
        assert!(catalog(&json!({"item_data_list":[{"item_id":"1"},{"item_id":"1"}]})).is_err());
        assert!(catalog(&json!({"item_data_list":[{"title":"x"}]})).is_err());
    }
    #[test]fn chapter_rejects_ciphertext_missing_and_partial_text(){
        for content in ["a".repeat(120),"暂缺".to_string(),"\u{e001}".repeat(100)]{
            assert!(chapter(&json!({"data":{"item_infos":{"1":{"content":content}}}}),"2","1","第一章").is_err());
        }
        assert!(chapter(&json!({"data":{"item_infos":{"1":{}}}}),"2","1","第一章").is_err());
    }
    #[test]fn chapter_strips_html_and_keeps_paragraphs(){
        let raw=json!({"data":{"item_infos":{"1":{"content":format!("<p>{}</p><p>第二段 &amp; 后续。</p>","正文内容。".repeat(30))}}}});
        let result=chapter(&raw,"2","1","第一章").unwrap();
        assert!(result["txtContent"].as_str().unwrap().contains("\n第二段 & 后续。"));
    }
}
