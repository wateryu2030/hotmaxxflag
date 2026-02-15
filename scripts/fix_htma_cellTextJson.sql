-- 修复 htma 报表 cellTextJson 为 null 导致的 NPE
-- 为数据行单元格添加 cellTextJson 空对象
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/fix_htma_cellTextJson.sql

USE jimureport;
SET NAMES utf8mb4;

-- 完整 json_str，每个 loopBlock 单元格包含 cellTextJson: {}
UPDATE jimu_report SET json_str = '{"loopBlockList":[{"sci":0,"sri":1,"eci":5,"eri":1,"index":1,"db":"htma_profit"}],"printConfig":{"paper":"A4","width":210,"height":297,"definition":1,"isBackend":false,"marginX":10,"marginY":10,"layout":"portrait"},"hidden":{"rows":[],"cols":[]},"dbexps":[],"dicts":[],"freeze":"A1","dataRectWidth":600,"autofilter":{},"validations":[],"cols":{"0":{"width":90},"1":{"width":80},"2":{"width":100},"3":{"width":100},"4":{"width":80},"5":{"width":100},"len":100},"area":{"sri":1,"sci":0,"eri":1,"eci":5,"width":100,"height":25},"pyGroupEngine":false,"excel_config_id":"8946110000000000001","hiddenCells":[],"zonedEditionList":[],"rows":{"0":{"cells":{"0":{"text":"日期"},"1":{"text":"品类"},"2":{"text":"总销售额"},"3":{"text":"总毛利"},"4":{"text":"毛利率"},"5":{"text":"门店"},"height":25}},"1":{"cells":{"0":{"text":"#{htma_profit.data_date}","loopBlock":1,"config":"","rendered":"","cellTextJson":{}},"1":{"text":"#{htma_profit.category}","loopBlock":1,"config":"","rendered":"","cellTextJson":{}},"2":{"text":"#{htma_profit.total_sale}","loopBlock":1,"config":"","rendered":"","cellTextJson":{}},"3":{"text":"#{htma_profit.total_profit}","loopBlock":1,"config":"","rendered":"","cellTextJson":{}},"4":{"text":"#{htma_profit.profit_rate}","loopBlock":1,"config":"","rendered":"","cellTextJson":{}},"5":{"text":"#{htma_profit.store_id}","loopBlock":1,"config":"","rendered":"","cellTextJson":{}}},"height":25},"len":200},"rpbar":{"show":true,"pageSize":"","btnList":[]}}'
WHERE id = '8946110000000000001';

SELECT ROW_COUNT() AS updated_rows, id, name FROM jimu_report WHERE id = '8946110000000000001';
