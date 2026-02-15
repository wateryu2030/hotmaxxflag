-- 将员工信息明细表(uiu)数据源改为本地 mock，无需公网
USE jimureport;
UPDATE jimu_report_db
SET api_url = 'http://127.0.0.1:8085/jmreport/api-proxy/mock/26/baobiao/ygtj?pageSize=''${pageSize}''&pageNo=''${pageNo}'''
WHERE id = 'b0f04c0f50a659f99c8aebe6efb93682' AND db_code = 'uiu';
