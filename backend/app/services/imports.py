from __future__ import annotations
import io
from datetime import datetime
from typing import Any
import pandas as pd
from backend.app.core.errors import DuplicateProjectCodeError, ValidationError
from backend.app.db.connection import get_connection
from backend.app.repositories import projects as project_repo
from backend.app.schemas.import_export import ImportCommitErrorItem, ImportPreviewErrorItem, ImportPreviewRecord
from backend.app.services.project_codes import generate_project_code, validate_manual_project_code
from backend.app.services.projects import create_project_internal

STATUS_MAP = {"未立项":"draft", "项目库—未实施":"established", "推进中":"established", "已完成":"closed", "已废弃":"terminated", "draft":"draft", "established":"established", "closed":"closed", "terminated":"terminated"}
ALIASES = {"project_code":["项目编号","project_code"],"name":["项目名称","name"],"status":["项目状态","当前状态","状态","current_status"],"project_type":["项目分类","项目类型","project_type"],"department":["申报部门","部门","department"],"major":["所属专业","专业","major"],"project_manager":["项目负责人","负责人","project_manager"],"sponsor":["发起人","sponsor"],"description":["项目说明","项目描述","description"],"special_note":["历史备注","特殊说明","special_note"],"budget":["初始预算","预算","预算(万元)","budget"],"approved_budget":["有效预算","审核后预算","approved_budget"],"procurement_nature":["采购属性","procurement_nature"],"location":["地点","location"],"establishment_document_no":["立项文件号"],"completed_on":["完成日期","实际结束日期"],"advancement_year":["推进年度"],"termination_reason":["废弃原因"],"approver":["审批人"]}
NATURES={"货物":"goods","服务":"service","混合":"mixed","goods":"goods","service":"service","mixed":"mixed"}

def _pick(row:dict[str,Any], field:str)->str:
    for key in ALIASES[field]:
        value=row.get(key,"")
        if value not in ("",None): return str(value).strip()
    return ""

def _date_like(value:str)->bool:
    parts=value.split("-")
    return bool(value) and len(parts) in {1,2,3} and all(x.isdigit() for x in parts) and len(parts[0])==4

def generate_import_template()->bytes:
    cols=["项目编号","项目名称","项目状态","项目分类","申报部门","所属专业","项目负责人","发起人","项目说明","历史备注","初始预算","有效预算","采购属性","地点","立项文件号","完成日期","推进年度","废弃原因","审批人"]
    with get_connection() as conn:
        type_rows = conn.execute("SELECT name,code_prefix FROM project_types WHERE is_active=1 ORDER BY sort_order,id").fetchall()
    formats = "；".join(f"{row['name']}：{row['code_prefix']}YYYYNNNN，例如 {row['code_prefix']}20250001" for row in type_rows)
    guide=[["字段","必填","适用状态","格式与示例"],["项目编号","选填","全部","留空按当前年份自动生成；手工历史编号须符合：" + formats + f"；YYYY 为 1900 至 {datetime.now().year}"],["项目名称","必填","全部","普通文本"],["项目状态","必填","全部","仅可填：未立项、项目库—未实施、推进中、已完成、已废弃"],["项目分类","必填","全部","填写启用分类名称，不填内部代码"],["初始预算","选填","全部","金额（万元）；空白代表未记录，0 代表真实零预算"],["有效预算","选填","全部","金额（万元）；写入历史审核预算来源，不覆盖初始预算"],["采购属性","选填","全部","货物、服务或混合"],["地点","选填","全部","普通文本"],["立项文件号","必填","项目库—未实施","普通文本"],["完成日期","必填","已完成","YYYY、YYYY-MM 或 YYYY-MM-DD；可晚于推进年度"],["推进年度","必填","推进中、已完成","四位实施年份，例如 2025，不从完成日期推断"],["废弃原因","必填","已废弃","普通文本"],["审批人","必填","已废弃","普通文本"]]
    output=io.BytesIO()
    with pd.ExcelWriter(output,engine="openpyxl") as writer:
        pd.DataFrame([["","示例项目","项目库—未实施","专业教学软件项目","信息中心","软件工程","李工","张主任","","","100","88.5","服务","","立项〔2026〕1号","","","",""]],columns=cols).to_excel(writer,index=False,sheet_name="项目数据")
        pd.DataFrame(guide[1:],columns=guide[0]).to_excel(writer,index=False,sheet_name="填写说明")
    return output.getvalue()

def _read_table(file_name:str,content:bytes)->pd.DataFrame:
    if file_name.lower().endswith(".csv"): return pd.read_csv(io.BytesIO(content),dtype=str).fillna("")
    workbook=io.BytesIO(content)
    try:
        return pd.read_excel(workbook,dtype=str,sheet_name="\u9879\u76ee\u6570\u636e").fillna("")
    except ValueError:
        # Legacy workbooks are readable for diagnostic preview, but only the
        # unified template has the headers required for a valid import.
        workbook.seek(0)
        return pd.read_excel(workbook,dtype=str,sheet_name=0).fillna("")

def _next_code(conn,project_type:str,reserved:set[str])->str:
    code=generate_project_code(conn,project_type); prefix,num=code[:-4],int(code[-4:])
    while code in reserved or project_repo.project_code_exists(conn,code): num+=1; code=f"{prefix}{num:04d}"
    return code

def preview_import(file_name:str,content:bytes)->dict:
    try: df=_read_table(file_name,content)
    except Exception as exc: raise ValidationError(f"无法读取文件：{exc}") from exc
    records=[]; errors=[]; reserved=set()
    manual_codes = [str(_pick(row, "project_code") or "").strip().upper() for row in df.to_dict("records")]
    with get_connection() as conn:
        types={r["name"]:r["code"] for r in conn.execute("SELECT code,name FROM project_types WHERE is_active=1")}
        for number,row in enumerate(df.to_dict("records"),2):
            try:
                name=_pick(row,"name"); label=_pick(row,"status"); kind=types.get(_pick(row,"project_type")); status=STATUS_MAP.get(label)
                if not name: raise ValidationError("项目名称不能为空")
                if not kind: raise ValidationError("项目分类不存在或已停用")
                if not status: raise ValidationError("项目状态仅可填：未立项、项目库—未实施、推进中、已完成、已废弃")
                document,year,completed,reason,approver=(_pick(row,x) for x in ("establishment_document_no","advancement_year","completed_on","termination_reason","approver"))
                if label=="项目库—未实施" and not document: raise ValidationError("项目库—未实施必须填写立项文件号")
                if label in {"推进中", "已完成"} and (not year.isdigit() or len(year)!=4): raise ValidationError("推进中、已完成必须填写四位推进年度")
                if status=="closed" and not _date_like(completed): raise ValidationError("已完成必须填写完成日期（YYYY、YYYY-MM 或 YYYY-MM-DD）")
                if status=="terminated" and (not reason or not approver): raise ValidationError("已废弃必须填写废弃原因和审批人")
                supplied=_pick(row,"project_code"); code=validate_manual_project_code(conn,supplied,kind,allow_historical_year=True) if supplied else _next_code(conn,kind,reserved)
                if supplied and manual_codes.count(supplied.strip().upper()) > 1: raise DuplicateProjectCodeError(f"工作簿内项目编号重复: {code}")
                if code in reserved or project_repo.project_code_exists(conn,code): raise DuplicateProjectCodeError(f"项目编号重复: {code}")
                reserved.add(code); nature=NATURES.get(_pick(row,"procurement_nature"),_pick(row,"procurement_nature"))
                if nature and nature not in {"goods","service","mixed"}: raise ValidationError("采购属性仅可填货物、服务或混合")
                initial,effective=_pick(row,"budget"),_pick(row,"approved_budget")
                records.append(ImportPreviewRecord(row_number=number,project_code=code,name=name,description=_pick(row,"description"),department=_pick(row,"department"),major=_pick(row,"major"),sponsor=_pick(row,"sponsor"),project_manager=_pick(row,"project_manager"),current_status=status,project_type=kind,budget=float(initial) if initial else None,approved_budget=float(effective) if effective else None,procurement_nature=nature,location=_pick(row,"location"),establishment_document_no=document,actual_end_date=completed,advancement_year=int(year) if year else None,import_advancing=label in {"推进中", "已完成"},termination_reason=reason,approver=approver,special_note=_pick(row,"special_note")))
            except Exception as exc: errors.append(ImportPreviewErrorItem(row_number=number,code=getattr(exc,"code","IMPORT_PREVIEW_ERROR"),message=str(exc),name=_pick(row,"name") or None))
    return {"total_rows":len(df),"valid_rows":len(records),"invalid_rows":len(errors),"records":records,"errors":errors}


def _commit_validation_errors(conn, records:list[ImportPreviewRecord]) -> list[ImportCommitErrorItem]:
    errors=[]; reserved=set()
    for record in records:
        try:
            if not record.name.strip(): raise ValidationError("项目名称不能为空")
            if record.current_status not in set(STATUS_MAP.values()): raise ValidationError("项目状态无效")
            if record.current_status == "established" and not record.import_advancing and not record.establishment_document_no: raise ValidationError("项目库—未实施必须填写立项文件号")
            if (record.import_advancing or record.current_status == "closed") and record.advancement_year is None: raise ValidationError("推进中、已完成必须填写四位推进年度")
            if record.current_status == "closed" and not _date_like(record.actual_end_date): raise ValidationError("已完成必须填写完成日期（YYYY、YYYY-MM 或 YYYY-MM-DD）")
            if record.current_status == "terminated" and (not record.termination_reason or not record.approver): raise ValidationError("已废弃必须填写废弃原因和审批人")
            code=validate_manual_project_code(conn,record.project_code,record.project_type,allow_historical_year=True)
            if code in reserved or project_repo.project_code_exists(conn,code): raise DuplicateProjectCodeError(f"项目编号重复: {code}")
            reserved.add(code)
        except Exception as exc:
            errors.append(ImportCommitErrorItem(row_number=record.row_number,name=record.name,code=getattr(exc,"code","IMPORT_PREVIEW_ERROR"),message=str(exc)))
    return errors

def commit_import(records:list[ImportPreviewRecord],operator:str)->dict:
    if not records: raise ValidationError("没有可导入项目")
    with get_connection() as conn:
        errors=_commit_validation_errors(conn,records)
        if errors: return {"total":len(records),"success":0,"failed":len(errors),"errors":errors}
        for record in records:
            project=create_project_internal(
                {**record.model_dump(),"operator":operator},
                conn=conn,
                allow_historical_project_code=True,
            )
            if record.import_advancing:
                now=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                record_status = "completed" if record.current_status == "closed" else "active"
                conn.execute("INSERT INTO project_advancement_records (project_id,advancement_year,status,included_at,included_reason,included_by,ended_at,ended_reason,ended_by) VALUES (?,?,?,?,?,?,?,?,?)",(project["id"],record.advancement_year,record_status,now,"历史项目导入",operator,now if record_status == "completed" else None,"历史项目已完成" if record_status == "completed" else "",operator if record_status == "completed" else ""))
                project_repo.update_project_status(conn,project["id"],{"library_implementation_view":"advancing" if record_status == "active" else "unimplemented","advancement_year":record.advancement_year,"advancement_date":now,"updated_at":now})
    return {"total":len(records),"success":len(records),"failed":0,"errors":[]}
