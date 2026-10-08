// Offline behavior checks; does not automate or render a browser.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../gui/index.html'), 'utf8');
let source = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1].replace(
  /model\.pageSize=50;renderLogs\(\);[^\n]*/,
  'window.api={rowOperation,selectGridAxis,renderTrimPattern,patternSearchMatches,openPatternPicker,movePatternWrite,patternValueMode,renderPatternValue,setPatternMode,patternItem,changePattern,setPatternValue,patternFields,choosePatternAddress,patternAction,draftPayload,diagnosticFixes,openDiagnosticFix,applyDiagnosticFix,moveFlowGroup,flowGroup,moveRecipeModule,openRecipe,applyRecipe,recipeText,model,selectedColumns,changes,pasteValues,editCell,check,save,generate,pollJob,renderJobResult,restoreDraft,saveDraft,snapshot,commitBefore,filteredRows,loadFile,addRow,sheet,renderDiagnostics,locateDiagnostic,openGroupCopy,confirmGroupCopy,openOutput,previewFile,searchCode,openBatchFill,previewBatchFill,applyBatchFill,renderLinks,followLink,returnToFlow,renderTable,sheetSections,selectSheetSection,selectGridCell,gridSelection,copyGridText,parseGridText,changeGridRange,gridMoveAddress,setGridDimension,gridDimension};');
source=source.replace('window.api={','window.api={openResourceWizard,saveResourceWizard,cancelResourceWizard,changeFlowEditStructure,selectFlowEditPhase,saveFlowPhaseEdit,changeFlowPhase,flowGroupPhases,refreshFlowFields,openFlowItemEdit,saveFlowItemEdit,renderFlowWizard,configureFlowPattern,openFlowWizard,setFlowWizardField,nextFlowWizard,finishFlowWizard,cancelFlowWizard,');
// Optional argument: a real /api/state JSON snapshot. Default fixture keeps checks standalone.
source=source.replace('window.api={','window.api={patternTargetMatches:typeof patternTargetMatches==="function"?patternTargetMatches:null,');
const integrationState = process.argv[2] ? JSON.parse(fs.readFileSync(process.argv[2], 'utf8')) : null;
let state = {
  name:'test.xlsx',sha256:'fixture',diagnostics:[],targets:[{id:'chroma-cp1'},{id:'s100-cp1'}],
  sheets:[{name:'VERSION',rows:[],columns:[],maxRow:0,maxCol:0},
    {name:'FLOW',maxRow:60,maxCol:25,appendableRows:Array.from({length:59},(_,i)=>i+2),columns:Array.from({length:25},(_,i)=>({label:String(i+1)})),
      rows:Array.from({length:60},(_,r)=>Array.from({length:25},(_,c)=>({
        value:r===3&&c===18?.8:null,formula:null,editable:r>0}))) }]
};
const results = [];
function setup() {
  const nodes = new Map(), handlers = {}, storage = new Map(), timers = new Map();let timerId=0;
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {textContent:'', innerHTML:'', value:'', disabled:false,
      classList:{add(){}, toggle(){}}, addEventListener(name,fn){this[name]=fn;}, appendChild(child){child.parentElement=this;}, showModal(){this.open=true;}, close(){this.open=false;}});
    return nodes.get(id);
  };
  node('connection').textContent=JSON.stringify({token:state.testToken||'test'});
  const context = {window:{addEventListener(name, fn){handlers[name]=fn;}}, document:{getElementById:node, querySelector(){return null;},querySelectorAll(){return [];},
    addEventListener(name, fn){handlers[name]=fn;}}, Headers, console, confirm:()=>true,
    setTimeout(fn){timers.set(++timerId,fn);return timerId;}, clearTimeout(id){timers.delete(id);}, localStorage:{
      setItem(k,v){storage.set(k,v);}, getItem(k){return storage.get(k);}},
    fetch:async()=>{throw Error('No mocked response');}};
  vm.runInNewContext(source, context);
  const api=context.window.api, m=api.model;
  m.state=structuredClone(state);m.sheetIndex=m.state.sheets.findIndex(s=>s.name==='FLOW');
  const reply=body=>({ok:true,status:200,headers:new Headers({'content-type':'application/json'}),json:async()=>body});
  return {api,m,node,context,storage,handlers,reply,runTimer:async id=>{const fn=timers.get(id);assert.ok(fn,'expected pending timer');timers.delete(id);return fn();}};
}
async function test(name, fn){try{await fn();results.push([name,true]);}catch(e){results.push([name,false,e.message]);}}
(async()=>{
  await test('Assistant snapshot uses visible unsaved values and keeps the full draft',()=>{
    const {api,m,context}=setup();
    api.editCell({dataset:{edit:'S4'},value:'0.801'});
    const snapshot=context.window.MCUProgram.assistantSnapshot();
    assert.equal(snapshot.selectedSheet.rows[3][18].value,'0.801');
    assert.equal(snapshot.draft.changes[0].value,'0.801');
    assert.equal(snapshot.selectedSheet.rows[3][18].editable,undefined);
    assert.equal(m.state.sheets[m.sheetIndex].rows[3][18].value,.8);
  });
  await test('Pattern Link names survive draft persistence and undo without a visible sheet',()=>{
    const {api,m,node}=setup();
    const record={cp:'CP3',item:'ADC',phase:'ADC1',role:'config',platform:'shared',original:'old',pattern:'source'};
    m.patternLinks=[record];api.saveDraft();
    assert.equal(api.draftPayload().patternLinks[0].pattern,'source');
    m.patternLinks=[];api.restoreDraft();assert.equal(m.patternLinks[0].pattern,'source');
    node('undo-btn').onclick();assert.equal(m.patternLinks.length,0);
    assert.ok(!m.state.sheets.some(s=>s.name==='Pattern Link'));
  });
  await test('Empty workbench can render before an Excel is opened',async()=>{
    const {api,m}=setup();m.state={loaded:false,sha256:'',sheets:[],targets:[],diagnostics:[],links:{}};m.sheetIndex=0;
    api.renderTable();api.renderDiagnostics([]);assert.equal(api.sheet(),undefined);assert.equal(api.draftPayload().baseSha256,'');
  });
  await test('Resource edit locates selected direction, retains other values and undoes one save',async()=>{
    const {api,m,node,context,reply}=setup();m.state.sheets.push({name:'PVD',maxRow:3,maxCol:2,resourceRows:[2,3],columns:[{label:'case'},{label:'limit'}],rows:[[{value:'case'},{value:'limit'}],[{value:'1',editable:true},{value:'30mV',editable:true}],[{value:'1',editable:true},{value:'30mV',editable:true}]]});m.sheetIndex=2;
    const before=JSON.stringify(api.snapshot());let sent;
    context.fetch=async(url,o)=>{sent=JSON.parse(o.body);return reply(sent.action==='resource-options'?{columns:['case','limit'],templates:[{label:'1',rows:[2,3],records:[{case:'1',limit:'30mV'},{case:'1',limit:'30mV'}],editable:[[true,true],[true,true]]}]}:{ready:true,row:2,count:2,draft:{...api.draftPayload(),changes:[{sheet:'PVD',cell:'B3',old:'30mV',value:'31mV'}],appendRows:[],flowOrder:[],trimStorageMappings:[],verifyStorageMappings:[],patternEdits:[]}});};
    await api.openResourceWizard(3);assert.equal(sent.editRow,3);assert.equal(m.resourceWizard.index,1);assert.equal(node('resource-new-save').textContent,'检查并保存修改');
    node('resource-new-content').oninput({target:{dataset:{resourceField:'limit'},value:'31mV'}});
    assert.equal(m.resourceWizard.records[0].limit,'30mV');await api.saveResourceWizard();assert.equal(sent.editRow,3);assert.equal(m.appendRows.length,0);assert.equal(m.undo.length,1);
    node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('ADC IOMUX mapping is explicit, editable and cancelled without draft mutations',async()=>{
    const {api,m,node,context,reply}=setup(),before=JSON.stringify(api.snapshot());
    const records=Array.from({length:22},(_,i)=>({ADC:'ADC1',Chanel:String(i)}));
    m.resourceWizard={sheet:'ADC',state:m.state,revision:m.revision,index:0,template:{records,rows:[2]},records:structuredClone(records),options:{columns:['ADC','Chanel'],templates:[],iomuxPins:[{row:3,pin:'PA01',analog:'ADC1_IN0/ADC12_IN1'},{row:4,pin:'PA02',analog:'ADC1_IN2'}]}};
    node('resource-new-content').onclick({target:{dataset:{iomuxAction:'toggle'}}});
    assert.ok(m.resourceWizard.iomuxRows.every(r=>r===null));
    node('resource-new-content').onclick({target:{dataset:{iomuxAction:'template'}}});
    assert.deepEqual(Array.from(m.resourceWizard.iomuxRows.slice(0,3)),[3,3,4]);
    node('resource-new-content').onchange({target:{dataset:{iomuxChannel:'0'},value:'4'}});
    assert.equal(m.resourceWizard.iomuxRows[0],4);
    let payload;context.fetch=async(url,options)=>{payload=JSON.parse(options.body);return reply({ready:false,issues:[{message:'missing pin'}]});};
    await assert.rejects(api.saveResourceWizard(),/missing pin/);assert.equal(payload.iomuxRows[0],4);
    api.cancelResourceWizard();assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('Resource creation saves one transaction, restores draft and preserves FLOW row offsets',async()=>{
    const {api,m,node,context,reply,storage}=setup();
    m.state.sheets.push({name:'DAC',maxRow:2,maxCol:2,resourceRows:[2],columns:[{label:'mode'},{label:'code'}],rows:[[{value:'mode'},{value:'code'}],[{value:'BUFFOFF',editable:true},{value:'0x001',editable:true}]]});
    m.sheetIndex=2;const before=JSON.stringify(api.snapshot());
    context.fetch=async(url,options)=>{const p=JSON.parse(options.body);return reply(p.action==='resource-options'?{columns:['mode','code'],templates:[{label:'DAC',rows:[2],records:[{mode:'BUFFOFF',code:'0x001'}]}]}:{ready:true,row:3,count:1,draft:{...api.draftPayload(),changes:[{sheet:'DAC',cell:'A3',old:null,value:'BUFFOFF'},{sheet:'DAC',cell:'B3',old:null,value:'0x003'}],appendRows:[{sheet:'DAC',sourceRow:2,copy:false}],flowOrder:[],trimStorageMappings:[],verifyStorageMappings:[],patternEdits:[]}});};
    await api.openResourceWizard();const content=node('resource-new-content').innerHTML;
    node('resource-new-content').oninput({target:{dataset:{resourceField:'code'},value:'0x003'}});
    node('resource-new-content').onchange({target:{id:''}});
    assert.equal(node('resource-new-content').innerHTML,content);
    await api.saveResourceWizard();assert.equal(api.sheet().maxRow,3);assert.equal(m.undo.length,1);
    api.saveDraft();const saved=[...storage];node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
    for(const [k,v] of saved)storage.set(k,v);api.restoreDraft();assert.equal(api.sheet().maxRow,3);
    m.sheetIndex=1;api.addRow(false);assert.equal(api.sheet().maxRow,61);assert.equal(m.appendRows.length,2);
  });
  await test('PVD group identity and step synchronize while thresholds remain per direction',()=>{
    const {m,node}=setup();m.resourceWizard={sheet:'PVD',index:0,records:[{case:'1',step:'1',min:'2.8'},{case:'1',step:'1',min:'2.7'}]};
    const input=(k,value)=>node('resource-new-content').oninput({target:{dataset:{resourceField:k},value}});
    input('case','8');input('step','2');input('min','2.9');
    assert.equal(m.resourceWizard.records[1].case,'8');assert.equal(m.resourceWizard.records[1].step,'2');assert.equal(m.resourceWizard.records[1].min,'2.7');
  });
  await test('Existing stages add, delete, reorder and commit one structural draft',async()=>{
    const {api,m,context,reply,node}=setup(),s=api.sheet();
    ['CP NO','item','relay','sub','type','Recipe','mode'].forEach((x,i)=>s.columns[i].label=x);
    for(const r of [3,4])['CP1','Firmware','/',String(r),'verify','RUN_SEQUENCE-JUDGE','keil'].forEach((v,i)=>s.rows[r-1][i].value=v);
    let payload;context.fetch=async(url,options)=>{payload=JSON.parse(options.body);return reply(payload.action==='validate-edit'?{ready:true}:{kind:'VERIFY_KEIL',fields:[],editRows:[3,4]});};
    const before=JSON.stringify(api.snapshot());api.openFlowItemEdit(4);await api.refreshFlowFields();
    await api.changeFlowEditStructure('add');assert.equal(m.flowWizard.editPhases.length,3);assert.ok(m.flowWizard.editRow<0);
    api.setFlowWizardField('sub','new_run');await api.changeFlowEditStructure('up');await api.selectFlowEditPhase(3);await api.changeFlowEditStructure('delete');
    await api.saveFlowPhaseEdit();assert.equal(m.appendRows.length,1);assert.equal(m.undo.length,1);
    assert.deepEqual(Array.from(m.flowOrder.slice(0,4)),[1,2,61,4]);assert.equal(payload.changes.find(c=>c.cell==='D61').value,'new_run');
    node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('Existing phase groups preserve raw values, share explicit edits and undo atomically',async()=>{
    const {api,m,node,context,reply}=setup(),s=api.sheet();
    ['CP NO','item','relay','sub','type','Recipe','mode','Hbin','Sbin','target'].forEach((x,i)=>s.columns[i].label=x);
    for(const row of [3,4])['CP1','Firmware','/',row===3?'download':'run','verify',row===3?'':'RUN_SEQUENCE-JUDGE',row===3?'hex':'keil','12','13','HH'].forEach((v,i)=>s.rows[row-1][i].value=v);
    const initial=JSON.stringify(api.snapshot());let payload;
    context.fetch=async(url,options)=>{payload=JSON.parse(options.body);return reply(payload.action==='validate-edit'?{ready:true}:{kind:'VERIFY_KEIL',editGuided:true,fields:[],editRows:[3,4]});};
    api.openFlowItemEdit(4);await api.refreshFlowFields();assert.equal(m.flowWizard.editPhases.length,2);
    api.setFlowWizardField('Hbin','15');api.setFlowWizardField('target','LL');
    await api.selectFlowEditPhase(3);assert.equal(m.flowWizard.values.Hbin,'15');assert.equal(m.flowWizard.values.target,'HH');assert.equal(m.flowWizard.values.Recipe,'');
    await api.saveFlowPhaseEdit();assert.equal(payload.action,'validate-edit');assert.equal(m.undo.length,1);
    assert.equal(m.draft.get('FLOW!H3').value,'15');assert.equal(m.draft.get('FLOW!H4').value,'15');assert.equal(m.draft.get('FLOW!J4').value,'LL');assert.ok(!m.draft.has('FLOW!F3'));
    node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),initial);
  });
  await test('Group edit rejects compile errors, protected shared cells and stale/cancelled replies',async()=>{
    const {api,m,context,reply}=setup(),s=api.sheet();s.columns[1].label='item';
    context.fetch=async()=>reply({kind:'VERIFY_KEIL',fields:[],editRows:[3,4]});
    api.openFlowItemEdit(3);await api.refreshFlowFields();const before=JSON.stringify(api.snapshot());
    m.flowWizard.editPhases[1].fields[1].editable=false;api.setFlowWizardField('item','Shared');
    await assert.rejects(api.saveFlowPhaseEdit(),/只读/);assert.equal(JSON.stringify(api.snapshot()),before);
    m.flowWizard.editPhases[1].fields[1].editable=true;context.fetch=async()=>reply({ready:false,issues:[{message:'bad stage'}]});
    await assert.rejects(api.saveFlowPhaseEdit(),/bad stage/);assert.equal(JSON.stringify(api.snapshot()),before);
    let resolve;context.fetch=()=>new Promise(r=>resolve=r);const pending=api.saveFlowPhaseEdit();m.revision++;resolve(reply({ready:true}));await assert.rejects(pending,/草稿已变化/);
    m.flowWizard.revision=m.revision;const cancelled=api.saveFlowPhaseEdit();api.cancelFlowWizard();resolve(reply({ready:true}));await cancelled;assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('Stage groups preserve per-phase values, shared bins, order and atomic undo',async()=>{
    const {api,m,context,reply,node}=setup();const before=JSON.stringify(api.snapshot());api.openFlowWizard();
    api.setFlowWizardField('_template','FIRMWARE_GROUP');api.setFlowWizardField('item','Firmware_New');
    api.setFlowWizardField('Vcc','VCC_TYP');api.setFlowWizardField('step','download_a');api.setFlowWizardField('Hbin','12');
    context.fetch=async()=>reply({kind:'VERIFY_KEIL',specialized:true,supported:true,fields:[],issues:[]});
    await api.changeFlowPhase('add');assert.equal(m.flowWizard.values.mode,'keil');assert.equal(m.flowWizard.values.Vcc,'VCC_TYP');
    api.setFlowWizardField('step','PA0:HL-5ms');api.setFlowWizardField('sub','run');
    await api.changeFlowPhase('select',0);assert.equal(m.flowWizard.values.step,'download_a');
    await api.changeFlowPhase('select',1);assert.equal(m.flowWizard.values.step,'PA0:HL-5ms');
    await api.changeFlowPhase('up');assert.equal(api.flowGroupPhases()[0].sub,'run');
    await api.changeFlowPhase('down');assert.equal(api.flowGroupPhases()[0].step,'download_a');
    const row=api.sheet().maxRow+1;
    m.flowWizard.prepared={ready:true,row:3,draft:{changes:[],appendRows:[{sheet:'FLOW',sourceRow:2,copy:false},{sheet:'FLOW',sourceRow:2,copy:false}],flowOrder:[1,2,row,row+1,...Array.from({length:row-3},(_,i)=>i+3)],trimStorageMappings:[],verifyStorageMappings:[],patternEdits:[]}};
    api.finishFlowWizard();assert.equal(m.appendRows.length,2);assert.equal(m.undo.length,1);
    node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('Power profiles select min typ max and retain custom values in new and existing forms',async()=>{
    const {api,m,node,context,reply}=setup();api.openFlowWizard();
    m.flowWizard.step=3;m.flowWizard.view={fields:[{name:'Vcc',label:'供电配置',required:true}]};
    context.fetch=async()=>reply({fields:[{name:'Vcc',label:'供电配置',required:true}]});
    api.renderFlowWizard();assert.match(node('flow-new-content').innerHTML,/data-flow-vcc/);
    for(const profile of ['MIN','TYP','MAX']){
      node('flow-new-content').onchange({target:{dataset:{flowVcc:''},value:'VCC_'+profile,tagName:'SELECT'}});
      assert.equal(m.flowWizard.values.Vcc,'VCC_'+profile);
      assert.match(node('flow-new-content').innerHTML,new RegExp('value="VCC_'+profile+'" selected>'+profile.toLowerCase()));
    }
    node('flow-new-content').onchange({target:{dataset:{flowVcc:''},value:'custom',tagName:'SELECT'}});
    assert.match(node('flow-new-content').innerHTML,/<input[^>]*data-flow-field="Vcc"/);
    node('flow-new-content').oninput({target:{dataset:{flowField:'Vcc'},value:'3.1V',tagName:'INPUT'}});
    api.renderFlowWizard();assert.equal(m.flowWizard.values.Vcc,'3.1V');
    assert.match(node('flow-new-content').innerHTML,/value="3.1V"/);
    api.cancelFlowWizard();const s=api.sheet();s.columns[23].label='Vcc';s.rows[2][23].value='custom_supply';
    api.openFlowItemEdit(3);m.flowWizard.step=3;api.renderFlowWizard();
    assert.match(node('flow-new-content').innerHTML,/value="custom" selected>自由输入/);
    assert.equal(m.flowWizard.values.Vcc,'custom_supply');api.saveFlowItemEdit();assert.equal(m.draft.size,0);
  });
  await test('ADC has one template with a single default stage and optional additional stages',async()=>{
    const {api,m,node,context,reply}=setup();api.openFlowWizard();
    api.setFlowWizardField('_template','ADC_TEST');api.renderFlowWizard();
    const content=node('flow-new-content').innerHTML;
    assert.match(content,/<option value="ADC_TEST"[^>]*>ADC 测试<\/option>/);
    assert.doesNotMatch(content,/value="ADC_GROUP"/);
    assert.equal(m.flowWizard.values._group,'adc');
    assert.equal(api.flowGroupPhases().length,1);
    context.fetch=async()=>reply({kind:'ADC_TEST',specialized:true,supported:true,fields:[],issues:[]});
    await api.changeFlowPhase('add');api.setFlowWizardField('FV/FI','ADC2');
    assert.equal(api.flowGroupPhases().length,2);
    assert.equal(api.flowGroupPhases()[0]['FV/FI'],'ADC1');
    await api.changeFlowPhase('delete');assert.equal(api.flowGroupPhases().length,1);
  });
  await test('ADC mode changes synchronize stage and Recipe while preserving the selected channel group',async()=>{
    const {api,m,node}=setup();api.openFlowWizard();api.setFlowWizardField('_template','ADC_TEST');
    api.setFlowWizardField('FV/FI','ADC3');api.setFlowWizardField('item','ads');
    node('flow-new-content').onchange({target:{dataset:{flowField:'mode'},tagName:'SELECT',value:'keil'}});
    assert.equal(m.flowWizard.values._phaseKind,'ADC_KEIL_DIGITAL');
    assert.equal(m.flowWizard.values.Recipe,'RUN_SEQUENCE-JUDGE');
    assert.match(node('flow-new-content').innerHTML,/ADC_KEIL_SRAM/);
    api.setFlowWizardField('_phaseKind','ADC_KEIL_SRAM');
    assert.equal(m.flowWizard.values.mode,'keil');
    assert.equal(m.flowWizard.values['FV/FI'],'ADC3');
    assert.match(m.flowWizard.values.Recipe,/RUN_SEQUENCE-SRAM_CAPTURE/);
    api.setFlowWizardField('Recipe','RUN_SEQUENCE-SRAM_CAPTURE(0x20000000,22x16@2)-ADC_JUDGE');
    api.setFlowWizardField('mode','keil');
    assert.match(m.flowWizard.values.Recipe,/0x20000000/);
    api.setFlowWizardField('mode','swd');
    assert.equal(m.flowWizard.values._phaseKind,'ADC_SWD');
    assert.equal(m.flowWizard.values.Recipe,'SWD_CAPTURE-ADC_JUDGE');
    assert.equal(m.flowWizard.values.item,'ads');assert.equal(m.flowWizard.values['FV/FI'],'ADC3');
    assert.equal(api.flowGroupPhases()[0].mode,'swd');
    api.setFlowWizardField('mode','keil');
    assert.equal(api.flowGroupPhases()[0].Recipe,'RUN_SEQUENCE-JUDGE');
  });
  await test('Analog presets retain production Recipe and route to their own resource sheet',async()=>{
    const {api,m,node}=setup();api.openFlowWizard();
    for(const [kind,recipe,mode] of [['ADC_TEST','SWD_CAPTURE-ADC_JUDGE','swd'],['OPA_TEST','OPA_TEST','swd'],['DAC_TEST','DAC_TEST','swd'],['PVD_TEST','PVD_TEST','keil']]){
      api.setFlowWizardField('_template',kind);
      assert.equal(m.flowWizard.values.Recipe,recipe);assert.equal(m.flowWizard.values.mode,mode);
      m.flowWizard.view={specialized:true,kind,resourceSheet:kind.split('_')[0],resources:['sheet data']};
      m.flowWizard.step=1;api.renderFlowWizard();
      assert.ok(node('flow-new-content').innerHTML.includes('data-configure-flow-sheet="'+kind.split('_')[0]+'"'));
      assert.doesNotMatch(node('flow-new-content').innerHTML,/data-flow-pattern/);m.flowWizard.step=0;
    }
  });
  await test('Specialized FLOW templates skip ordinary selectors and preserve fixed protocol values',async()=>{
    const {api,m,node,context,reply}=setup();api.openFlowWizard();
    api.setFlowWizardField('_template','PDR_TRIM');assert.equal(m.flowWizard.values.item,'Pdr_Trim');
    api.setFlowWizardField('_template','FREQ_TEST');assert.equal(m.flowWizard.values['FV/FI'],'FREQ');assert.equal(m.flowWizard.values.mode,'swd');
    api.setFlowWizardField('_template','OS');assert.equal(m.flowWizard.values.mode,'/');assert.equal(m.flowWizard.values.item,'');
    api.setFlowWizardField('item','os_extra');
    context.fetch=async()=>reply({kind:'OS',specialized:true,supported:true,issues:[],fields:[],positions:[{before:3,label:'before'}],fixedValues:{target:'/',OTP:'no',UID:'no',PUMP:'no',Recipe:''},resources:['原生开短路协议']});
    await api.nextFlowWizard();assert.equal(m.flowWizard.step,1);assert.equal(m.flowWizard.values.target,'/');
    assert.match(node('flow-new-content').innerHTML,/原生开短路协议/);assert.doesNotMatch(node('flow-new-content').innerHTML,/data-flow-pattern/);
    await api.nextFlowWizard();assert.equal(m.flowWizard.step,2);assert.match(node('flow-new-content').innerHTML,/均为 no/);
    await api.nextFlowWizard();assert.equal(m.flowWizard.step,3);assert.equal(m.flowWizard.targets.length,0);
    api.cancelFlowWizard();assert.equal(m.appendRows.length,0);
  });
  await test('FLOW shared descriptor preserves old values and validates edited units atomically',async()=>{
    const {api,m,node,context,reply}=setup(),s=api.sheet();
    ['CP NO','item','relay','sub','type','Recipe','mode','UNIT','PUMP','DAC bit'].forEach((x,i)=>s.columns[i].label=x);
    ['CP1','Existing','/','/','trim','','fbist','V','yes','4'].forEach((x,i)=>s.rows[3][i].value=x);
    context.fetch=async()=>reply({kind:'STANDARD_VERIFY',supported:true,editGuided:true,issues:[],fields:[{name:'UNIT',label:'单位',choices:['V','MHz'],required:true}],clearFields:['DAC bit']});
    const before=JSON.stringify(api.snapshot());api.openFlowItemEdit(4);await api.refreshFlowFields();
    api.setFlowWizardField('type','verify');assert.equal(m.flowWizard.values.PUMP,'yes');assert.equal(m.flowWizard.values['DAC bit'],'4');
    m.flowWizard.step=3;await api.refreshFlowFields();assert.match(node('flow-new-content').innerHTML,/不使用的字段/);
    assert.match(node('flow-new-content').innerHTML,/aria-required="true"/);
    api.setFlowWizardField('UNIT','mV');await api.refreshFlowFields();assert.throws(()=>api.saveFlowItemEdit(),/不支持 mV/);assert.equal(JSON.stringify(api.snapshot()),before);
    api.setFlowWizardField('UNIT','MHz');await api.refreshFlowFields();api.saveFlowItemEdit();assert.equal(m.undo.length,1);assert.ok(!m.draft.has('FLOW!I4'));assert.ok(!m.draft.has('FLOW!J4'));
    node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('FLOW descriptor ignores stale responses and cancellation, advanced Recipe keeps every field',async()=>{
    const {api,m,node,context,reply}=setup();context.fetch=async()=>reply({kind:'STANDARD_VERIFY',editGuided:false,fields:[],clearFields:[],notice:'复杂 Recipe'});
    api.openFlowItemEdit(4);await api.refreshFlowFields();m.flowWizard.step=3;api.renderFlowWizard();assert.ok(!node('flow-new-content').innerHTML.includes('data-clear-flow-inactive'));
    let resolve;context.fetch=()=>new Promise(r=>resolve=r);const pending=api.refreshFlowFields();api.setFlowWizardField('item','Changed');resolve(reply({kind:'OLD',editGuided:true}));await pending;assert.notEqual(m.flowWizard.view.kind,'OLD');
    const cancelled=api.refreshFlowFields();api.cancelFlowWizard();resolve(reply({kind:'OLD'}));await cancelled;assert.equal(m.flowWizard,null);
  });
  await test('Refreshing FLOW rules never replaces a field while the next value is being typed',async()=>{
    const {api,m,node,context,reply}=setup();context.fetch=async()=>reply({kind:'STANDARD_VERIFY',editGuided:true,fields:[],clearFields:[]});
    api.openFlowItemEdit(4);await api.refreshFlowFields();const original=node('flow-new-content').innerHTML;
    context.document.activeElement={dataset:{flowField:'target'}};
    let resolve;context.fetch=()=>new Promise(r=>resolve=r);const pending=api.refreshFlowFields();
    api.setFlowWizardField('target','');resolve(reply({kind:'STANDARD_VERIFY',fields:[]}));await pending;
    assert.equal(m.flowWizard.values.target,'');assert.equal(node('flow-new-content').innerHTML,original);
  });
  await test('Existing FLOW form preserves raw Recipe, mappings, row identity and commits once',()=>{
    const {api,m,node}=setup(),s=api.sheet();['CP NO','item','relay','sub','type','Recipe'].forEach((x,i)=>s.columns[i].label=x);
    s.rows[3][0].value='CP1';s.rows[3][1].value='Existing';s.rows[3][4].value='trim';s.rows[3][5].value='ENTER-DEPEND(Other)-TRIM-DAC_ADJ(<1.16:+1)-JUDGE';
    m.draft.set('FLOW!S4',{sheet:'FLOW',cell:'S4',old:.8,value:'1.2'});
    const before=JSON.stringify(api.snapshot());api.openFlowItemEdit(4);assert.equal(m.flowWizard.values['19'],'1.2');
    api.cancelFlowWizard();assert.equal(JSON.stringify(api.snapshot()),before);
    api.openFlowItemEdit(4);api.saveFlowItemEdit();assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(m.undo.length,0);
    api.openFlowItemEdit(4);api.setFlowWizardField('19','1.3');api.setFlowWizardField('relay','K1');api.saveFlowItemEdit();
    assert.equal(m.undo.length,1);assert.equal(m.appendRows.length,0);assert.equal(m.draft.get('FLOW!S4').value,'1.3');assert.ok(!m.draft.has('FLOW!F4'));
    node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
    m.flowOrder=Array.from({length:s.maxRow},(_,i)=>i+1);[m.flowOrder[2],m.flowOrder[3]]=[4,3];
    api.openFlowItemEdit(3);api.setFlowWizardField('relay','K2');api.saveFlowItemEdit();assert.equal(m.draft.get('FLOW!C4').value,'K2');
    api.openFlowItemEdit(3);m.revision++;assert.throws(()=>api.saveFlowItemEdit(),/过期/);
  });
  await test('FLOW edit form handles appended rows and rejects protected changes atomically',()=>{
    const {api,m}=setup(),s=api.sheet();s.columns[0].label='CP NO';s.columns[1].label='item';s.columns[4].label='type';
    s.rows[3][1].editable=false;api.openFlowItemEdit(4);api.setFlowWizardField('19','2');api.setFlowWizardField('item','blocked');
    const before=JSON.stringify(api.snapshot());assert.throws(()=>api.saveFlowItemEdit(),/只读/);assert.equal(JSON.stringify(api.snapshot()),before);
    api.cancelFlowWizard();m.selectedRow=3;api.addRow(false);const count=m.appendRows.length,row=api.sheet().maxRow;
    api.openFlowItemEdit(row);api.setFlowWizardField('item','New_Row_Edit');api.saveFlowItemEdit();
    assert.equal(m.appendRows.length,count);assert.equal(m.draft.get('FLOW!B'+row).value,'New_Row_Edit');
  });
  await test('FLOW measurement defaults require unit and target and derive editable force from unit',()=>{
    const {api,m,node}=setup();api.openFlowWizard();const v=m.flowWizard.values;
    m.flowWizard.step=3;m.flowWizard.view={fields:['FV/FI','low_range(%)','UNIT','target'].map(name=>({name,label:name}))};api.renderFlowWizard();
    const markup=node('flow-new-content').innerHTML;assert.ok(markup.indexOf('data-flow-field="UNIT"')<markup.indexOf('data-flow-field="target"'));assert.ok(markup.indexOf('data-flow-field="target"')<markup.indexOf('data-flow-field="FV/FI"'));
    assert.ok(!v.UNIT);assert.ok(!v.target);assert.equal(v['low_range(%)'],'1%');assert.equal(v['high_range(%)'],'1%');
    for(const [unit,force] of [['V','0uA'],['mV','0uA'],['uA','0V'],['mA','0V'],['KHz','/'],['MHz','/'],['pat',''],['','']]){
      api.setFlowWizardField('UNIT',unit);assert.equal(v['FV/FI'],force);
    }
    api.setFlowWizardField('UNIT','V');api.setFlowWizardField('FV/FI','10uA');api.setFlowWizardField('target','1.2');
    api.setFlowWizardField('UNIT','V');assert.equal(v['FV/FI'],'10uA');assert.equal(v.target,'1.2');
    api.setFlowWizardField('UNIT','uA');assert.equal(v['FV/FI'],'0V');
  });
  await test('Selecting FLOW storage fields keeps DOM scroll and search while updating count',()=>{
    const {api,m,node}=setup();api.openFlowWizard();const w=m.flowWizard;
    w.step=2;w.values.type='verify';w.values._storageMode='map';w.values._search_storage='FLASH*';
    w.view={storage:[{page:'trim0',register:'FLASH0',field:'A'},{page:'uid',register:'B',field:'B'}]};
    api.renderFlowWizard();const markup=node('flow-new-content').innerHTML;
    assert.ok(markup.includes('id="flow-selected-storage"'));assert.ok(markup.indexOf('id="flow-selected-storage"')<markup.indexOf('data-flow-field="_search_storage"'));
    const content=node('flow-new-content');content.scrollTop=180;
    Object.defineProperty(content,'innerHTML',{get:()=>'',set:()=>{throw Error('selection rebuilt scroll containers');}});
    for(const [index,checked,count] of [[0,true,1],[1,true,2],[0,false,1],[1,false,0]]){
      w.prepared={ready:true};content.onchange({target:{dataset:{flowTarget:String(index)},checked}});
      assert.equal(node('flow-selected-storage').textContent,w.targets.map(t=>t.page+' / '+t.register+' / '+t.field).join('；'));
      assert.equal(content.scrollTop,180);assert.equal(w.targets.length,count);assert.equal(w.prepared,null);
      assert.equal(w.values._search_storage,'FLASH*');assert.match(node('flow-storage-count').textContent,new RegExp('已选 '+count+' 个字段'));
    }
    assert.equal(node('flow-selected-storage').textContent,'');
  });
  await test('Selecting FLOW Pattern keeps list DOM and scroll position while updating its title',()=>{
    const {api,m,node}=setup();api.openFlowWizard();m.flowWizard.step=1;
    const content=node('flow-new-content');content.scrollTop=180;
    Object.defineProperty(content,'innerHTML',{get:()=>'',set:()=>{throw Error('selection rebuilt scroll containers');}});
    for(const [field,value] of [['_enterPattern','enter_vrefbuf2p5'],['_dacPattern','set_vrefbuf2p5_dac']]){
      content.onchange({target:{dataset:{flowPattern:field},value}});
      assert.equal(m.flowWizard.values[field],value);assert.equal(node('flow-selected-'+field).textContent,value);
      assert.equal(content.scrollTop,180);
    }
  });
  await test('Saving a linked resource automatically returns with the submitted draft and refreshed resources',async()=>{
    const {api,m,node,context,reply}=setup();m.state.sheets.push({name:'DAC',maxRow:2,maxCol:1,resourceRows:[2],columns:[{label:'mode'}],rows:[[{value:'mode'}],[{value:'BUFFOFF',editable:true}]]});
    api.openFlowWizard();const w=m.flowWizard;w.values.item='DAC_User';w.values.target='4096';w.step=1;w.resumeStep=1;w.suspended=true;w.resourceSheet='DAC';w.values._template='DAC_TEST';node('flow-new-dialog').close();m.sheetIndex=2;
    let refresh;context.fetch=async(url,o)=>{const p=JSON.parse(o.body);if(p.action==='resource-options')return reply({columns:['mode'],templates:[{rows:[2],records:[{mode:'BUFFOFF'}]}]});if(p.action==='resource-prepare')return reply({ready:true,row:3,count:1,draft:{...api.draftPayload(),changes:[{sheet:'DAC',cell:'A3',old:null,value:'BUFFON'}],appendRows:[{sheet:'DAC',sourceRow:2,copy:false}],flowOrder:[],trimStorageMappings:[],verifyStorageMappings:[],patternEdits:[]}});refresh=p;return reply({supported:true,specialized:true,kind:'DAC_TEST',resources:['2 cases'],positions:[]});};
    await api.openResourceWizard();await api.saveResourceWizard();assert.equal(m.flowWizard,w);assert.equal(w.suspended,false);assert.equal(node('flow-new-dialog').open,true);assert.equal(w.values.target,'4096');assert.equal(w.step,1);assert.equal(refresh.appendRows.length,1);assert.equal(w.view.resources[0],'2 cases');assert.equal(m.undo.length,1);
  });
  await test('Return ignores cancelled responses and invalidates removed Pattern choices',async()=>{
    const {api,m,node,context,reply}=setup();api.openFlowWizard();let w=m.flowWizard;w.step=1;w.suspended=true;w.values._enterPattern='removed';node('flow-new-dialog').close();
    context.fetch=async()=>reply({supported:true,patterns:{enter:[],dac:[]},positions:[]});await api.openFlowWizard();assert.equal(w.values._enterPattern,'');assert.match(w.error,/Pattern/);
    w.suspended=true;node('flow-new-dialog').close();let resolve;context.fetch=()=>new Promise(r=>resolve=r);const pending=api.openFlowWizard();api.cancelFlowWizard();resolve(reply({supported:true,patterns:{enter:[],dac:[]}}));await pending;assert.equal(m.flowWizard,null);assert.equal(node('flow-new-dialog').open,false);
  });
  await test('Resource return preserves wizard step parameters storage selection and insertion position',async()=>{
    const {api,m,node,context,reply}=setup();api.openFlowWizard();const w=m.flowWizard;
    w.values.item='Keep';w.values.target='1.23';w.step=3;w.suspended=true;w.resumeStep=3;w.before=9;w.targets=[{page:'otp',register:'R',field:'F'}];w.prepared={ready:true};node('flow-new-dialog').close();m.revision++;
    context.fetch=async()=>reply({supported:true,kind:'STANDARD_TRIM',fields:[],patterns:{enter:[],dac:[]},positions:[{before:9,label:'Keep position'}],currentTargets:[]});
    await api.openFlowWizard();assert.equal(w.step,3);assert.equal(w.values.target,'1.23');assert.equal(w.before,9);assert.equal(w.targets.length,1);assert.equal(w.prepared,null);assert.equal(w.revision,m.revision);
  });
  await test('FLOW Pattern configuration opens existing item creator and resumes with refreshed resources',async()=>{
    const {api,m,node,context,reply}=setup();m.state.sheets.push({name:'pattern',rows:[],columns:[],maxRow:0,maxCol:4});m.state.patternItems=[];
    api.openFlowWizard();api.setFlowWizardField('item','Keep_Me');const w=m.flowWizard;w.step=1;
    const before=JSON.stringify(api.snapshot());api.configureFlowPattern('dac');
    assert.equal(node('flow-new-dialog').open,false);assert.equal(node('pattern-new-dialog').open,true);
    assert.equal(node('pattern-new-purpose').value,'trim dac');assert.equal(api.sheet().name,'pattern');
    assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(w.values.item,'Keep_Me');
    node('pattern-new-dialog').close();m.revision++;
    context.fetch=async()=>reply({kind:'STANDARD_TRIM',supported:true,issues:[],fields:[],patterns:{enter:[],dac:[{name:'new_dac'}]},positions:[],currentTargets:[]});
    await api.openFlowWizard();assert.equal(m.flowWizard,w);assert.equal(w.step,1);assert.equal(w.values.item,'Keep_Me');
    assert.equal(w.view.patterns.dac[0].name,'new_dac');assert.equal(w.revision,m.revision);
    assert.match(node('flow-new-content').innerHTML,/data-configure-flow-pattern="enter"/);
    assert.match(node('flow-new-content').innerHTML,/data-configure-flow-pattern="dac"/);
    assert.match(node('flow-new-content').innerHTML,/进入配置：<strong id="flow-selected-_enterPattern"><\/strong>/);
    assert.match(node('flow-new-content').innerHTML,/DAC 配置：<strong id="flow-selected-_dacPattern"><\/strong>/);
  });
  await test('New FLOW wizard cancels without rows and ignores late resource responses',async()=>{
    const {api,m,node,context,reply}=setup();const flow=m.state.sheets.find(s=>s.name==='FLOW');
    flow.columns[0].label='CP NO';flow.columns[1].label='item';flow.columns[4].label='type';
    const before=JSON.stringify(api.snapshot());
    api.openFlowWizard();assert.equal(m.flowWizard.step,0);assert.equal(node('flow-new-dialog').open,true);
    api.setFlowWizardField('item','Wizard_New');
    let resolve;context.fetch=()=>new Promise(r=>{resolve=r});
    const pending=api.nextFlowWizard();assert.match(node('flow-new-content').innerHTML,/<fieldset[^>]+disabled/);api.cancelFlowWizard();
    resolve(reply({kind:'STANDARD_TRIM',supported:true,issues:[],fields:[],patterns:{enter:[],dac:[]},storage:[],positions:[],currentTargets:[]}));
    await pending;assert.equal(m.flowWizard,null);assert.equal(node('flow-new-dialog').open,false);
    assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('New FLOW wizard commits one complete draft and undoes all changes once',()=>{
    const {api,m,node}=setup();const flow=m.state.sheets.find(s=>s.name==='FLOW'),row=flow.maxRow+1;
    flow.columns[0].label='CP NO';flow.columns[1].label='item';flow.columns[4].label='type';
    const before=JSON.stringify(api.snapshot());api.openFlowWizard();api.setFlowWizardField('item','Wizard_New');
    m.flowWizard.step=4;m.flowWizard.prepared={ready:true,row:3,draft:{changes:[{sheet:'FLOW',cell:'A'+row,old:null,value:'CP1'},{sheet:'FLOW',cell:'B'+row,old:null,value:'Wizard_New'}],appendRows:[{sheet:'FLOW',sourceRow:2,copy:false}],flowOrder:[1,2,row,...Array.from({length:flow.maxRow-2},(_,i)=>i+3)],trimStorageMappings:[{item:'Wizard_New',targets:[]}],verifyStorageMappings:[],patternEdits:[]}};
    api.finishFlowWizard();assert.equal(m.flowWizard,null);assert.equal(m.appendRows.length,1);assert.equal(m.undo.length,1);assert.equal(m.check,null);
    assert.equal(m.flowOrder[2],row);assert.equal(m.draft.get('FLOW!B'+row).value,'Wizard_New');
    node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
    api.openFlowWizard();m.flowWizard.values._enterPattern='old';m.flowWizard.values._dacPattern='old_dac';m.flowWizard.targets=[{page:'uid',register:'r',field:'f'}];
    api.setFlowWizardField('type','verify');assert.equal(m.flowWizard.values._enterPattern,undefined);assert.equal(m.flowWizard.targets.length,0);
  });
  await test('Links follow moved row identities and show copied Recipe mappings immediately',()=>{
    const {api,m,node}=setup();const flow=m.state.sheets.find(s=>s.name==='FLOW');
    ['CP NO','item','relay','sub','type','Recipe'].forEach((label,i)=>flow.columns[i].label=label);
    m.state.links=[{flowRow:3,cp:'CP1',item:'first',kind:'TRIM',patterns:[]},{flowRow:4,cp:'CP1',item:'second',kind:'TRIM',patterns:[]}];
    flow.rows[2][0].value='CP1';flow.rows[2][1].value='first';flow.rows[2][4].value='trim';flow.rows[3][0].value='CP1';flow.rows[3][1].value='second';flow.rows[3][4].value='trim';
    m.flowOrder=Array.from({length:flow.maxRow},(_,i)=>i+1);[m.flowOrder[2],m.flowOrder[3]]=[4,3];m.selectedRow=4;api.renderLinks();
    assert.match(node('linked-body').innerHTML,/<strong>first<\/strong>/);assert.ok(!node('linked-body').innerHTML.includes('<strong>second</strong>'));
    m.draft.set('FLOW!B3',{sheet:'FLOW',cell:'B3',old:'first',value:'copy'});m.draft.set('FLOW!F3',{sheet:'FLOW',cell:'F3',old:null,value:'ENTER(PATTERN=enter_first)-TRIM(PATTERN=set_first_dac)-JUDGE'});
    api.renderLinks();assert.match(node('linked-body').innerHTML,/当前草稿映射/);assert.match(node('linked-body').innerHTML,/set_first_dac/);assert.match(node('linked-body').innerHTML,/copy/);
  });
  await test('Context row insert and delete keep identities and undo as single operations',()=>{
    const {api,m,node}=setup();m.section=null;const base=api.sheet(),count=base.maxRow;
    api.rowOperation('above',4);assert.equal(api.sheet().maxRow,count+1);assert.equal(m.flowOrder[3],count+1);assert.equal(m.selectedRow,4);assert.equal(m.undo.length,1);
    api.editCell({dataset:{edit:'B4'},value:'inserted'});assert.equal(m.draft.get('FLOW!B'+(count+1)).value,'inserted');
    const before=m.undo.length;api.rowOperation('delete',4);assert.equal(api.sheet().maxRow,count);assert.ok(!m.flowOrder.includes(count+1));assert.equal(m.undo.length,before+1);
    node('undo-btn').onclick();assert.equal(api.sheet().maxRow,count+1);assert.equal(m.draft.get('FLOW!B'+(count+1)).value,'inserted');
    api.saveDraft();m.flowOrder=[];api.restoreDraft();assert.equal(m.flowOrder[3],count+1);
    api.rowOperation('copy',4);assert.equal(m.flowOrder[4],count+2);assert.equal(m.draft.get('FLOW!B'+(count+2)).value,'inserted_Copy1');
  });
  await test('Header clicks select all visible row or column cells',()=>{
    const {api,m,node}=setup();api.renderTable();
    api.selectGridAxis('row',4);let range=api.gridSelection();assert.deepEqual(Array.from(range.rows),[4]);assert.deepEqual(Array.from(range.cols),Array.from(api.selectedColumns(api.sheet())));
    const col=range.cols[0];node('table-host').onclick({target:{closest(selector){return selector==='[data-select-column]'?{dataset:{selectColumn:String(col)}}:null;}}});
    range=api.gridSelection();assert.deepEqual(Array.from(range.cols),[col]);assert.ok(range.rows.length>1);
    assert.match(node('table-host').innerHTML,/data-row-header="4"/);assert.match(node('table-host').innerHTML,/data-select-column=/);
  });
  await test('New TRIM row exposes mapping even when compilation has no links',()=>{
    const {api,m,node}=setup();const flow=m.state.sheets.find(s=>s.name==='FLOW');
    ['CP NO','item','relay','sub','type','Recipe'].forEach((label,i)=>flow.columns[i].label=label);
    const row=flow.maxRow+1;m.appendRows=[{sheet:'FLOW',sourceRow:2,copy:false}];
    for(const [col,value] of [['A','CP1'],['B','test'],['E','trim']])m.draft.set('FLOW!'+col+row,{sheet:'FLOW',cell:col+row,old:null,value});
    m.selectedRow=row;m.check={revision:m.revision,result:{valid:false,links:[]}};
    api.renderLinks();assert.match(node('linked-body').innerHTML,/data-trim-pattern/);
    assert.match(node('linked-body').innerHTML,/编辑 Pattern 映射/);assert.equal(m.check.result.valid,false);
  });
  await test('Flow mapping sidebar keeps repeated RUN identities and searches dependency descriptions',()=>{
    const {api,m,node}=setup();m.trimPatternView={row:4,item:'Test',cp:'CP1',revision:m.revision,recipeText:'RUN(a)-RUN(b)-DEPEND(Source)-TRIM',uses:[
      {step:0,module:'RUN',current:'a',options:[{name:'a'},{name:'b'}]},
      {step:1,module:'RUN',current:'b',options:[{name:'a'},{name:'b'}]},
      {step:2,module:'DEPEND',current:'Source',options:[{name:'Source',description:'set_source_dac'},{name:'Other',description:'set_other_dac'}]},
      {step:3,module:'TRIM',current:'dac',options:[{name:'dac'}]}]};
    api.renderTrimPattern();assert.match(node('trim-pattern-tabs').innerHTML,/步骤 1 · a/);assert.match(node('trim-pattern-tabs').innerHTML,/步骤 2 · b/);
    node('trim-pattern-tabs').onclick({target:{closest(){return {dataset:{trimPatternTab:'1'}};}}});
    assert.match(node('trim-pattern-uses').innerHTML,/data-trim-pattern-select="1"/);assert.ok(!node('trim-pattern-uses').innerHTML.includes('data-trim-pattern-reset'));
    node('trim-pattern-tabs').onclick({target:{closest(){return {dataset:{trimPatternTab:'2'}};}}});
    node('trim-pattern-search').value='*other*';node('trim-pattern-search-btn').onclick();
    assert.match(node('trim-pattern-uses').innerHTML,/set_other_dac/);assert.ok(!node('trim-pattern-uses').innerHTML.includes('data-trim-pattern-name="Source"'));
    node('trim-pattern-search').value='missing';node('trim-pattern-search').onkeydown({key:'Enter',preventDefault(){}});
    assert.match(node('trim-pattern-uses').innerHTML,/没有匹配结果/);
    node('trim-pattern-tabs').onclick({target:{closest(){return {dataset:{trimPatternTab:'3'}};}}});
    assert.equal(node('trim-pattern-search').value,'');assert.match(node('trim-pattern-uses').innerHTML,/data-trim-pattern-reset="3"/);
    assert.equal(node('trim-pattern-recipe').textContent,m.trimPatternView.recipeText);
  });
  await test('Pattern mapping tabs show one purpose and preserve DAC selection on render',()=>{
    const {api,m,node}=setup();m.trimPatternView={row:4,item:'Test',cp:'CP1',revision:m.revision,uses:[
      {step:0,module:'ENTER',label:'进入测试模式',current:'enter_test',source:'default',options:[{name:'enter_test'}]},
      {step:2,module:'TRIM',label:'写 DAC',current:'set_test_dac',source:'default',options:[{name:'set_test_dac'}]}]};
    api.renderTrimPattern();assert.match(node('trim-pattern-tabs').innerHTML,/设置 DAC/);
    assert.match(node('trim-pattern-uses').innerHTML,/enter_test/);assert.ok(!node('trim-pattern-uses').innerHTML.includes('set_test_dac'));
    node('trim-pattern-tabs').onclick({target:{closest(){return {dataset:{trimPatternTab:'2'}};}}});
    assert.match(node('trim-pattern-uses').innerHTML,/set_test_dac/);assert.ok(!node('trim-pattern-uses').innerHTML.includes('enter_test'));
    api.renderTrimPattern();assert.equal(m.trimPatternStep,2);assert.match(node('trim-pattern-tabs').innerHTML,/data-trim-pattern-tab="2" aria-pressed="true"/);
  });
  await test('Double click enters edit from cell padding and survives focus selection',async()=>{
    const {m,node}=setup();let focused=0;let editingClass=false;node('table-host').classList.toggle=(name,on)=>{if(name==='cell-editing')editingClass=on;};
    const input={disabled:false,readOnly:false,focus(){focused++;m.cellEditing=false;},closest(selector){return selector==='[data-edit]'?this:null;}};
    const td={querySelector(){return input;}};
    const padding={closest(selector){return selector==='[data-cell]'?td:null;}};
    node('table-host').dblclick({target:padding,preventDefault(){}});
    assert.equal(focused,1,'double-click anywhere inside editable cell must focus its editor');assert.equal(m.cellEditing,true);assert.equal(editingClass,true);
    m.cellEditing=false;node('table-host').dblclick({target:input,preventDefault(){}});assert.equal(m.cellEditing,true,'focus must not reset editing mode');
    input.disabled=true;m.cellEditing=false;node('table-host').dblclick({target:padding,preventDefault(){}});assert.equal(m.cellEditing,false);
  });
  await test('FB search supports contains wildcards and treats punctuation literally',async()=>{
    const {api,node,m}=setup();
    assert.equal(api.patternSearchMatches('*TRIM*','BG_ABS_TRIM_VDDK'),true);
    assert.equal(api.patternSearchMatches('*trim*','PMU_TMODE'),false);
    assert.equal(api.patternSearchMatches('trim','BG_ABS_TRIM_VDDK'),true);
    assert.equal(api.patternSearchMatches('*A[3:0]*','REG_A[3:0]_X'),true);
    assert.equal(api.patternSearchMatches('*A[3:0]*','REG_A3_X'),false);
    m.patternPicker={targets:[{id:'hit',address:'0000000',name:'BG_ABS_TRIM_VDDK',high:3,low:0},{id:'miss',address:'0000001',name:'PMU_TMODE',high:3,low:0}]};
    node('pattern-address-search').value='*TRIM*';node('pattern-address-search-btn').onclick();
    assert.match(node('pattern-addresses').innerHTML,/BG_ABS_TRIM/);assert.ok(!node('pattern-addresses').innerHTML.includes('PMU_TMODE'));
    node('pattern-address-search').value='*TMODE*';let prevented=false;node('pattern-address-search').onkeydown({key:'Enter',preventDefault(){prevented=true;}});
    assert.equal(prevented,true);assert.match(node('pattern-addresses').innerHTML,/PMU_TMODE/);
  });
  await test('Pattern picker reuses loaded FB targets and refreshes only changed FB drafts',async()=>{
    const {api,m,node,context,reply}=setup();
    m.section='First';m.state.patternItems=[{item:'First',editable:true,groups:[{role:'trim mode',steps:[]}]}];
    m.state.patternTargets=[{id:'old',address:'0000000',name:'OLD',high:0,low:0}];
    let calls=0;context.fetch=async()=>{calls++;return reply({targets:[{id:'new',address:'0000001',name:'NEW',high:1,low:1}]});};
    await api.openPatternPicker(0);assert.equal(calls,0,'unchanged FB MAP must open without re-reading Excel');
    assert.match(node('pattern-addresses').innerHTML,/OLD/);
    m.draft.set('FB MAP!B2',{sheet:'FB MAP',cell:'B2',value:'new'});
    await api.openPatternPicker(0);assert.equal(calls,1);assert.match(node('pattern-addresses').innerHTML,/NEW/);
    await api.openPatternPicker(0);assert.equal(calls,1,'same FB draft should reuse targets');
    m.draft.set('FB MAP!B2',{sheet:'FB MAP',cell:'B2',value:'newer'});
    await api.openPatternPicker(0);assert.equal(calls,2);
    m.draft.clear();await api.openPatternPicker(0);assert.equal(calls,2);assert.match(node('pattern-addresses').innerHTML,/OLD/);
    m.draft.set('FB MAP!B2',{sheet:'FB MAP',cell:'B2',value:'pending'});
    let finish;context.fetch=()=>new Promise(resolve=>{finish=resolve;});
    const pending=api.openPatternPicker(0);assert.equal(node('pattern-picker-dialog').open,true);assert.match(node('pattern-addresses').innerHTML,/正在读取/);
    node('pattern-picker-close').onclick();finish(reply({targets:[]}));await pending;
    assert.equal(node('pattern-picker-dialog').open,false);assert.equal(m.patternPicker,null,'late response must not reopen cancelled picker');
    m.draft.clear();const immediate=api.openPatternPicker(0);assert.equal(node('pattern-picker-dialog').open,true);assert.match(node('pattern-addresses').innerHTML,/OLD/);await immediate;

  });
  await test('Pattern item edits preserve write order, pending values, merged export view and undo drafts',async()=>{
    const {api,m,node,storage,context,reply}=setup();
    const rows=[['item','addr','description','pattern'],['First','0100010','2,trg=0','trim mode'],[null,'0100010','2,trg=1',null]];
    m.state.sheets.push({name:'pattern',headerRows:1,maxRow:3,maxCol:4,columns:rows[0].map(label=>({label})),rows:rows.map((r,i)=>r.map(value=>({value,editable:i>0,formula:null}))),merges:[{minRow:2,maxRow:3,minCol:1,maxCol:1},{minRow:2,maxRow:3,minCol:4,maxCol:4}]});
    m.state.patternItems=[{item:'First',start:2,end:3,editable:true,groups:[{role:'trim mode',steps:[{sourceRow:2,addr:'0100010',description:'2,trg=0'},{sourceRow:3,addr:'0100010',description:'2,trg=1'}]}]}];
    m.state.patternTargets=[{id:'trg',address:'0100010',name:'trg',register:'reg',high:2,low:2,width:1}];
    api.selectSheetSection(m.state.sheets.length-1,'First');assert.match(node('table-host').innerHTML,/pattern-business/);assert.match(node('table-host').innerHTML,/添加 FB 写入/);
    const wide=api.renderPatternValue({value:'xxxxxxxxxxxx',width:12,high:11,low:0},'0:0:0','wide','');
    assert.ok(!wide.includes('初值全 0'));assert.match(wide,/<option value="placeholder" selected>动态值<\/option>/);
    assert.match(wide,/<details class="pattern-bit-settings" data-pattern-bit-settings="0:0:0"><summary>逐位设置<\/summary>/);
    assert.equal((wide.match(/data-pattern-bit="/g)||[]).length,12);
    assert.match(api.renderPatternValue({value:'01xx',width:4,high:3,low:0},'0:0:0','mixed',''),/当前混合位：<code>01xx<\/code>/);
    const typing={dataset:{patternValue:'0:0:0'},value:'1',closest(){return this;}};
    node('table-host').input({target:typing});
    assert.equal(api.patternItem('First').groups[0].steps[0].description,'2,trg[0:0]=1');
    node('table-host').focusout({target:typing});node('undo-btn').onclick();
    assert.equal(api.patternItem('First').groups[0].steps[0].description,'2,trg=0');
    assert.match(node('table-host').innerHTML,/data-pattern-drag="0:0"/);
    assert.match(node('table-host').innerHTML,/<span class="pattern-write-fields" title="trg">trg<\/span>/);
    assert.ok(!node('table-host').innerHTML.includes('重新选择 FB 字段'));
    assert.match(node('table-host').innerHTML,/删除写入<\/button><\/summary>/);
    const undoCount=m.undo.length;api.movePatternWrite('First',0,0,0,false);assert.equal(m.undo.length,undoCount);
    assert.throws(()=>api.movePatternWrite('First',0,0,20),/已变化/);
    api.movePatternWrite('First',0,0,1,true);
    assert.equal(api.patternItem('First').groups[0].steps[0].description,'2,trg=1');
    m.patternPicker={name:'First',gi:0,si:null,state:m.state,revision:m.revision,targets:m.state.patternTargets};
    api.choosePatternAddress('0100010',['trg']);
    assert.equal(api.patternItem('First').groups[0].steps[2].description,'2,trg[0:0]=');
    assert.match(node('table-host').innerHTML,/待填写/);
    assert.throws(()=>api.setPatternValue('First',0,2,0,'11'),/需要 1 位/);
    api.setPatternValue('First',0,2,0,'0');assert.equal(api.draftPayload().patternEdits[0].groups[0].steps.length,3);
    assert.ok(api.sheet().merges.some(a=>a.minCol===1&&a.minRow===2&&a.maxRow===4));
    api.saveDraft();const saved=[...storage];node('undo-btn').onclick();assert.equal(api.patternItem('First').groups[0].steps[2].description,'2,trg[0:0]=');
    for(const [k,v] of saved)storage.set(k,v);api.restoreDraft();assert.equal(api.patternItem('First').groups[0].steps[2].description,'2,trg[0:0]=0');
    let sent;context.fetch=async(url,options)=>{sent=JSON.parse(options.body);return reply({path:'copy.xlsx'});};
    await node('draft-file-btn').onclick();assert.equal(sent.patternEdits[0].groups[0].steps.length,3);
    m.patternPicker={name:'First',gi:0,si:null,state:m.state,revision:m.revision-1,targets:m.state.patternTargets};
    assert.throws(()=>api.choosePatternAddress('0100010',['trg']),/过期/);
    api.changePattern('First',i=>{i.groups[0].steps[0].description='3,mode[3:0]=0101*';});
    assert.equal(api.patternValueMode('0101*'),'initial');
    assert.match(node('table-host').innerHTML,/data-pattern-initial="true"/);
    assert.ok(!node('table-host').innerHTML.includes('value="0101*"'));
    api.setPatternMode('First',0,0,0,'placeholder');assert.equal(api.patternItem('First').groups[0].steps[0].description,'3,mode[3:0]=xxxx');
    api.setPatternMode('First',0,0,0,'initial');assert.equal(api.patternItem('First').groups[0].steps[0].description,'3,mode[3:0]=*');
    const initInput={dataset:{patternValue:'0:0:0',patternInitial:'true'},value:'1010',closest(){return this;}};
    node('table-host').input({target:initInput});node('table-host').focusout({target:initInput});
    assert.equal(api.patternItem('First').groups[0].steps[0].description,'3,mode[3:0]=1010*');
    api.setPatternValue('First',0,0,0,'01xX*');assert.equal(api.patternValueMode('01xX*'),'mixed');assert.match(node('table-host').innerHTML,/data-pattern-bit=/);
    api.setPatternMode('First',0,0,0,'fixed');assert.equal(api.patternItem('First').groups[0].steps[0].description,'3,mode[3:0]=');
    node('undo-btn').onclick();assert.equal(api.patternItem('First').groups[0].steps[0].description,'3,mode[3:0]=01xX*');
    api.changePattern('Added',i=>i.groups.push({role:'trim mode',steps:[]}));api.selectSheetSection(m.sheetIndex,'Added');assert.equal(m.section,'Added');assert.match(node('table-host').innerHTML,/添加 FB 写入/);
  });
  await test('initial column widths follow longest content beyond the current page',()=>{
    const {api,m}=setup(),s=api.sheet();s.rows[59][1].value='W'.repeat(55);
    assert.ok(api.gridDimension('column',2)>400);
    assert.ok(api.gridDimension('column',3)<160);
    api.setGridDimension('column',2,250);assert.equal(api.gridDimension('column',2),250);
  });
  await test('merged cells span visible rows and columns and keep anchor identity after filtering',()=>{
    const {api,m,node}=setup(),s=api.sheet();m.columnMode='all';
    m.state.sheets[m.sheetIndex].merges=[{minRow:2,maxRow:3,minCol:2,maxCol:3}];s.rows[1][1].value='merged-anchor';
    api.renderTable();assert.match(node('table-host').innerHTML,/rowspan="2" colspan="2"/);
    assert.ok(!node('table-host').innerHTML.includes('data-cell="C2"'));
    assert.ok(!node('table-host').innerHTML.includes('data-cell="B3"'));
    assert.equal(api.gridMoveAddress('B2','ArrowRight'),'D2');
    assert.equal(api.gridMoveAddress('B2','ArrowDown'),'B4');
    assert.equal(api.gridMoveAddress('D3','ArrowLeft'),'B2');
    s.rows[2][3].value='only-third';m.query='only-third';api.renderTable();
    assert.match(node('table-host').innerHTML,/data-edit="B2"/);
    assert.match(node('table-host').innerHTML,/merged-anchor/);
  });
  await test('FLASH_EPR groups independent catalogs, omits empty records and retains edits and undo',()=>{
    const {api,m,node}=setup();
    m.state.sheets.push({name:'FLASH_EPR',headerRows:1,maxRow:2,maxCol:15,columns:['addr','configs','Description','mode','opr_mode','opr_value','space','page_num','chessboard_mode','chessboard_data','fbist_mode','fbist_cmd','comp_flag','comp_data','ecc'].map(label=>({label})),rows:[Array.from({length:15},()=>({value:'header',editable:false})),Array.from({length:15},()=>({value:'0',editable:true}))]});
    m.sheetIndex=m.state.sheets.length-1;api.renderTable();
    assert.match(node('table-host').innerHTML,/flash-groups/);
    assert.equal((node('table-host').innerHTML.match(/class="flash-group"/g)||[]).length,8);
    assert.equal((node('table-host').innerHTML.match(/data-edit=/g)||[]).length,15);
    const fs=api.sheet();fs.rows.push(Array.from({length:15},()=>({value:null,editable:true})));fs.maxRow=3;fs.rows[2][4].value='erase';api.renderTable();
    assert.match(node('table-host').innerHTML,/data-edit="F3"/);
    assert.ok(!node('table-host').innerHTML.includes('data-edit="A3"'));
    m.query='erase';api.renderTable();assert.match(node('table-host').innerHTML,/操作编码/);assert.ok(!node('table-host').innerHTML.includes('data-edit="A2"'));m.query='';api.renderTable();
    assert.match(node('table-host').innerHTML,/data-edit="O2"/);
    const before=api.snapshot();api.editCell({dataset:{edit:'O2'},value:'1'});api.commitBefore(before);
    assert.ok(api.changes().some(x=>x.sheet==='FLASH_EPR'&&x.cell==='O2'&&x.value==='1'));
    node('undo-btn').onclick();assert.equal(m.draft.size,0);
  });
  await test('KP RELAY stays in workbook state but is absent from sidebar without shifting sheet indices',()=>{
    const {api,m,node}=setup();
    m.state.sheets.splice(1,0,{name:'KP RELAY',rows:[],columns:[],maxRow:0,maxCol:0});m.sheetIndex=2;
    const before=JSON.stringify(m.state);api.renderTable();
    assert.ok(!node('sheet-list').innerHTML.includes('KP RELAY'));
    assert.ok(node('sheet-list').innerHTML.includes('data-sheet-index="2"'));
    assert.equal(node('sheet-count').textContent,'（'+m.state.sheets.filter(s=>!['KP RELAY','NM_pattern'].includes(s.name)).length+'）');
    assert.equal(api.sheet().name,'FLOW');assert.equal(JSON.stringify(m.state),before);
  });
  await test('diagnostic fixes recheck the complete draft and preserve unrelated edits',async()=>{
    const {api,m,node,context,reply}=setup(),s=m.state.sheets[m.sheetIndex];s.rows[3][1].value='x\u00a0y';
    m.draft.set('FLOW!B5',{sheet:'FLOW',cell:'B5',old:s.rows[4][1].value,value:'keep'});
    const ds=[{code:'PF.CHAR.NONBREAKING_SPACE',source:'PREFLIGHT',provenance:{sheet:'FLOW',coordinate:'B4'}}];
    m.busy=true;api.renderDiagnostics(ds);m.busy=false;assert.match(node('diagnostics').innerHTML,/修复此项/);
    let sent;context.fetch=async(url,opts)=>{assert.equal(url,'/api/check');sent=JSON.parse(opts.body);return reply({valid:false,diagnostics:[],errors:1,warnings:0});};
    node('fix-recheck').checked=true;api.openDiagnosticFix();await api.applyDiagnosticFix();assert.equal(sent.changes.length,2);assert.equal(m.draft.get('FLOW!B4').value,'x y');assert.equal(m.draft.get('FLOW!B5').value,'keep');
    node('undo-btn').onclick();assert.equal(m.draft.size,1);assert.equal(m.draft.get('FLOW!B5').value,'keep');
  });
  await test('diagnostic fix follows reordered FLOW identity and skips unknown punctuation',async()=>{
    const {api,m}=setup(),s=m.state.sheets[m.sheetIndex];s.rows[3][1].value='  value ';m.flowOrder=Array.from({length:s.maxRow},(_,i)=>i+1);[m.flowOrder[3],m.flowOrder[4]]=[m.flowOrder[4],m.flowOrder[3]];
    api.renderDiagnostics([{code:'PF.CHAR.OUTER_SPACE',source:'PREFLIGHT',provenance:{sheet:'FLOW',coordinate:'B5'}}]);api.openDiagnosticFix();await api.applyDiagnosticFix();assert.equal(m.draft.get('FLOW!B4').value,'value');assert.equal(api.changes()[0].cell,'B4');
  });

  await test('diagnostic fixes normalize curved quotes in ADDR_MAP numeric values and undo atomically',async()=>{
    const {api,m,node}=setup();const entries=[['I134',134,9,'32’h0000_FFFF',"32'h0000_FFFF"],['I135',135,9,'32’h0000_FFFF',"32'h0000_FFFF"],['I139',139,9,'32’h0000_FFFF',"32'h0000_FFFF"],['I140',140,9,'32’h0000_FFFF',"32'h0000_FFFF"],['F98',98,6,'16‘h0',"16'h0"],['F99',99,6,'“A”、B','"A"、B']];
    const sheet={name:'ADDR_MAP',maxRow:140,maxCol:9,columns:Array.from({length:9},(_,i)=>({label:String(i+1)})),rows:Array.from({length:140},()=>Array.from({length:9},()=>({value:null,formula:null,editable:true})))};
    m.state.sheets.push(sheet);for(const [,r,c,value] of entries)sheet.rows[r-1][c-1].value=value;
    api.renderDiagnostics(entries.map(([coordinate])=>({code:'PF.CHAR.FULLWIDTH',source:'PREFLIGHT',severity:'WARN',provenance:{sheet:'ADDR_MAP',coordinate}})));
    assert.equal(api.diagnosticFixes().length,entries.length);api.openDiagnosticFix();assert.equal(m.draft.size,0);
    await api.applyDiagnosticFix();for(const [cell,,,,expected] of entries)assert.equal(m.draft.get('ADDR_MAP!'+cell).value,expected);
    assert.equal(m.undo.length,1);node('undo-btn').onclick();assert.equal(m.draft.size,0);
    for(const [,r,c,value] of entries)assert.equal(sheet.rows[r-1][c-1].value,value);
  });
  await test('diagnostic fixes preview deduplicated edits and undo as one step',async()=>{
    const {api,m,node}=setup(),s=m.state.sheets[m.sheetIndex];s.rows[3][1].value=' ０.８％ ';
    const ds=['PF.CHAR.OUTER_SPACE','PF.CHAR.FULLWIDTH'].map(code=>({code,severity:'WARN',source:'PREFLIGHT',provenance:{sheet:'FLOW',coordinate:'B4'},message:code}));
    api.renderDiagnostics(ds);api.openDiagnosticFix();assert.equal(m.draft.size,0);assert.match(node('fix-preview').innerHTML,/0.8%/);
    await api.applyDiagnosticFix();assert.equal(m.draft.get('FLOW!B4').value,'0.8%');assert.equal(m.undo.length,1);
    node('undo-btn').onclick();assert.equal(m.draft.size,0);
  });
  await test('diagnostic fixes exclude ambiguous rules readonly formulas and stale reports',()=>{
    const {api,m}=setup(),s=m.state.sheets[m.sheetIndex];s.rows[3][1].value='０';
    const d={code:'PF.CHAR.FULLWIDTH',source:'PREFLIGHT',provenance:{sheet:'FLOW',coordinate:'B4'}};
    api.renderDiagnostics([d,{...d,code:'PF.FBMAP.ADDRESS_UNRESOLVED'}]);assert.equal(api.diagnosticFixes().length,1);
    s.rows[3][1].formula='=1';assert.equal(api.diagnosticFixes().length,0);s.rows[3][1].formula=null;s.rows[3][1].editable=false;assert.equal(api.diagnosticFixes().length,0);
    s.rows[3][1].editable=true;m.revision++;assert.equal(api.diagnosticFixes().length,0);
  });
  await test('diagnostic fix rejects stale preview and leaves unrelated draft intact',async()=>{
    const {api,m,node}=setup(),s=m.state.sheets[m.sheetIndex];s.rows[3][1].value='a\u200bb';
    api.renderDiagnostics([{code:'PF.CHAR.ZERO_WIDTH',source:'PREFLIGHT',provenance:{sheet:'FLOW',coordinate:'B4'}}]);
    api.openDiagnosticFix(0);m.revision++;await api.applyDiagnosticFix();assert.equal(m.draft.size,0);assert.match(node('fix-error').textContent,/过期/);
  });

  await test('FB MAP selection keeps two cell changes in one undo and rejects stale mapping',async()=>{
    const {api,m,node,context,reply}=setup();
    m.state.sheets.push({name:'pattern',maxRow:24,maxCol:4,headerRows:1,columns:[{label:'item'},{label:'addr'},{label:'description'},{label:'pattern'}],rows:Array.from({length:24},(_,r)=>Array.from({length:4},(_,c)=>({value:r===23?(c===1?'0000001':c===2?'3,IREF_TRIM[3:0]=0000*':null):null,editable:r>0})))});
    m.sheetIndex=m.state.sheets.length-1;m.selectedRow=24;
    const view={row:24,item:'Iref1u',role:'trim dac',output_pattern:'set_iref1u_dac',fields:[{line:0,name:'IREF_TRIM[3:0]',value:'0000',dynamic:true,high:3,low:0,width:4,current:null,status:'名称未匹配'}],targets:[{id:'new',name:'MR_TRIM_VDDK',register:'PMU_TRIM2',address:'0000010',high:7,low:4,width:4}]};
    let request;context.fetch=async(url,options)=>{request=JSON.parse(options.body);return reply('target' in request?{...view,changes:[{sheet:'pattern',cell:'B24',old:'0000001',value:'0000010'},{sheet:'pattern',cell:'C24',old:'3,IREF_TRIM[3:0]=0000*',value:'7,MR_TRIM_VDDK[3:0]=0000*'}],message:'局部校验通过'}:view);};
    await node('fb-map-btn').onclick();assert.equal(node('fb-map-dialog').open,true);
    assert.match(node('fb-map-target').innerHTML,/MR_TRIM_VDDK/);
    node('fb-map-field').value='0';node('fb-map-target').value='new';
    const goodFetch=context.fetch;context.fetch=async()=>({...reply({error:'位宽不一致'}),ok:false,status:400});await node('fb-map-apply').onclick();assert.equal(m.draft.size,0);assert.equal(m.undo.length,0);assert.match(node('fb-map-error').textContent,/位宽/);context.fetch=goodFetch;
    await node('fb-map-apply').onclick();assert.equal(request.target,'new');assert.equal(m.draft.size,2);assert.equal(m.undo.length,1);assert.match(api.changes().find(c=>c.cell==='C24').value,/0000\*/);
    node('undo-btn').onclick();assert.equal(m.draft.size,0);
    await node('fb-map-apply').onclick();assert.equal(m.draft.size,0);assert.match(node('fb-map-error').textContent,/过期|变化/);
  });
  await test('TRIM Pattern choice edits only the Recipe cell, rejects stale choice, and undoes once',async()=>{
    const {api,m,node,context,reply}=setup();m.linkRow=4;m.selectedRow=4;
    const flow=m.state.sheets.find(s=>s.name==='FLOW');flow.columns[5].label='Recipe';flow.rows[3][5].value='ENTER-TRIM-JUDGE';flow.columns[0].label='CP NO';flow.columns[1].label='item';flow.columns[4].label='type';flow.rows[3][4].value='trim';
    const view={row:4,cp:'CP1',item:'Hsi_8M',uses:[{step:0,module:'ENTER',label:'进入测试模式',current:'enter_hsi_8m',source:'按当前 item / 角色解析',explicit:false,options:[{name:'enter_hsi_8m',description:'old'},{name:'enter_hsi_16m',description:'new'}]}]};
    let request;
    context.fetch=async(url,options)=>{request=JSON.parse(options.body);return reply('pattern' in request?{...view,valid:true,pendingValidation:true,change:{sheet:'FLOW',cell:'F4',old:'ENTER-TRIM-JUDGE',value:'ENTER(PATTERN=enter_hsi_16m)-TRIM-JUDGE'},links:[]}:view);};
    await node('linked-body').onclick({target:{closest:selector=>selector==='[data-trim-pattern]'?{disabled:false}:null}});
    assert.equal(node('trim-pattern-dialog').open,true);assert.match(node('trim-pattern-uses').innerHTML,/enter_hsi_16m/);
    const success=context.fetch;context.fetch=async()=>reply({valid:false,diagnostics:[{severity:'ERROR',message:'Pattern 动态字段不兼容'}]});
    await node('trim-pattern-uses').onclick({target:{closest(){return {dataset:{trimPatternSelect:'0',trimPatternName:'enter_hsi_16m'}};}}});
    assert.equal(m.draft.size,0);assert.equal(m.undo.length,0);assert.match(node('trim-pattern-error').textContent,/不兼容/);context.fetch=success;
    await node('trim-pattern-uses').onclick({target:{closest(){return {dataset:{trimPatternSelect:'0',trimPatternName:'enter_hsi_16m'}};}}});
    assert.equal(request.pattern,'enter_hsi_16m');assert.equal(m.draft.size,1);assert.equal(m.undo.length,1);assert.match(api.changes()[0].value,/PATTERN=enter_hsi_16m/);
    assert.equal(m.mappingLinks,null);assert.equal(m.itemTimer,null);assert.equal(m.check,null);assert.equal(node('save-btn').disabled,true);
    node('undo-btn').onclick();assert.equal(m.draft.size,0);
    await node('trim-pattern-uses').onclick({target:{closest(){return {dataset:{trimPatternSelect:'0',trimPatternName:'enter_hsi_16m'}};}}});
    assert.equal(m.draft.size,0);assert.match(node('trim-pattern-error').textContent,/过期/);
  });
  function mappingSetup(){
    const env=setup(),{m}=env,flow=m.state.sheets.find(s=>s.name==='FLOW');
    flow.columns[0].label='CP NO';flow.columns[1].label='item';flow.columns[4].label='type';
    for(const [row,kind] of [[4,'trim'],[5,'verify']]){flow.rows[row-1][0].value='CP1';flow.rows[row-1][1].value='Vref';flow.rows[row-1][4].value=kind;}
    m.selectedRow=4;return env;
  }
  await test('clicking a physical field immediately maps TRIM and persists one undo step',async()=>{
    const {api,m,node,context,reply,storage}=mappingSetup();
    const target={page:'trim1',register:'REG_A',field:'BG_TC_TRIM_VDDK'};let request;
    context.fetch=async(url,options)=>{request=JSON.parse(options.body);return reply('targets' in request?
      {valid:true,trimStorageMappings:[{item:'Vref',targets:request.targets}],verifyStorageMappings:[],current:request.targets}:
      {row:4,cp:'CP1',cps:['CP1'],kind:'TRIM',item:'Vref',symbol:'VREF_DAC_FINAL',current:[],options:[{...target,width:5,lsb:0,source:'description'}]});};
    await node('workspace-mapping').onclick();
    assert.equal(node('mapping-page').hidden,false);assert.match(node('storage-flow').innerHTML,/TRIM/);assert.match(node('storage-flow').innerHTML,/VERIFY/);
    await node('storage-target').onclick({target:{closest:()=>({dataset:{storageTarget:'0'},disabled:false})}});
    assert.deepEqual(JSON.parse(JSON.stringify(request.targets)),[target]);assert.equal(m.trimStorageMappings[0].targets.length,1);assert.equal(m.undo.length,1);assert.equal(m.draft.size,0);
    assert.equal(m.verifyStorageMappings.length,0);assert.equal(m.check,null);assert.match(node('storage-target').innerHTML,/已映射/);
    api.saveDraft();assert.equal(JSON.parse([...storage.values()][0]).trimStorageMappings[0].targets[0].field,target.field);
    node('mapping-return').onclick();node('undo-btn').onclick();assert.equal(m.trimStorageMappings.length,0);
    node('redo-btn').onclick();assert.equal(m.trimStorageMappings[0].targets.length,1);
  });
  await test('VERIFY stores its result separately and unlinking last field is an explicit empty group',async()=>{
    const {m,node,context,reply}=mappingSetup();m.selectedRow=5;
    const target={page:'uid',register:'REG_V',field:'RESULT'};let request;
    context.fetch=async(url,options)=>{request=JSON.parse(options.body);return reply('targets' in request?
      {valid:true,trimStorageMappings:[],verifyStorageMappings:[{item:'Vref',targets:request.targets}],current:request.targets}:
      {row:5,cp:'CP1',kind:'VERIFY',item:'Vref',symbol:'VREF_EXPORT',current:[target],options:[{...target,width:16,lsb:0,source:'CP addr map'}]});};
    await node('workspace-mapping').onclick();
    assert.match(node('storage-item').textContent,/VERIFY.*VREF_EXPORT/);
    await node('storage-target').onclick({target:{closest:()=>({dataset:{storageTarget:'0'},disabled:false})}});
    assert.deepEqual(JSON.parse(JSON.stringify(request.targets)),[]);
    assert.equal(m.verifyStorageMappings.length,1);assert.equal(m.verifyStorageMappings[0].targets.length,0);assert.equal(m.trimStorageMappings.length,0);
  });
  await test('field click rejects conflicts and stale responses without modifying draft',async()=>{
    const {api,m,node,context,reply}=mappingSetup();
    context.fetch=async()=>reply({row:4,cp:'CP1',kind:'TRIM',item:'Vref',symbol:'VREF_DAC_FINAL',current:[],options:[{page:'p',register:'r',field:'F',width:5,lsb:0}]});
    await node('workspace-mapping').onclick();
    context.fetch=async()=>reply({valid:false,diagnostics:[{severity:'ERROR',message:'字段已被其他项占用'}]});
    await node('storage-target').onclick({target:{closest:()=>({dataset:{storageTarget:'0'},disabled:false})}});
    assert.equal(m.trimStorageMappings.length,0);assert.match(node('storage-error').textContent,/占用/);
    api.editCell({dataset:{edit:'S4'},value:'0.801'});
    await node('storage-target').onclick({target:{closest:()=>({dataset:{storageTarget:'0'},disabled:false})}});
    assert.match(node('storage-error').textContent,/过期/);assert.equal(m.trimStorageMappings.length,0);
  });
  await test('physical field filtering preserves selections and hardware names remain visible',async()=>{
    const {m,node,context,reply}=mappingSetup();
    const targets=[{page:'trim0',register:'A',field:'HW_A'},{page:'uid',register:'B',field:'HW_B'}];let request;
    context.fetch=async(url,options)=>{request=JSON.parse(options.body);return reply('targets' in request?
      {valid:true,trimStorageMappings:[{item:'Vref',targets:request.targets}],verifyStorageMappings:[],current:request.targets}:
      {row:4,cp:'CP1',kind:'TRIM',item:'Vref',symbol:'VREF_DAC_FINAL',current:targets,options:targets.map(t=>({...t,width:5,lsb:0,source:'description'}))});};
    await node('workspace-mapping').onclick();node('storage-filter').value='HW_B';node('storage-filter').oninput();
    assert.doesNotMatch(node('storage-target').innerHTML,/HW_A/);assert.match(node('storage-target').innerHTML,/HW_B/);
    await node('storage-target').onclick({target:{closest:()=>({dataset:{storageTarget:'1'},disabled:false})}});
    assert.deepEqual(JSON.parse(JSON.stringify(request.targets)),[targets[0]]);
  });
  await test('TRIM storage detail navigates ADDR_MAP without edits and rejects stale links',()=>{
    const {api,m,node}=setup();
    m.state.sheets.push({name:'ADDR_MAP',maxRow:12,maxCol:2,columns:[{label:'Word No.'},{label:'CP addr map'}],rows:Array.from({length:12},()=>[{value:'trim0',editable:true},{value:'field',editable:true}])});
    m.state.links=[{flowRow:4,cp:'CP1',item:'Example',kind:'TRIM',patterns:[],details:[{title:'ADDR_MAP 存储映射',summary:'已配置 · uid / Example',text:'EXAMPLE_DAC_FINAL → trim0 REG_A[6:4]',locations:[{sheet:'ADDR_MAP',coordinate:'B10',label:'查看 ADDR_MAP!B10'}]}]}];
    m.selectedRow=4;api.renderLinks();assert.match(node('linked-body').innerHTML,/REG_A\[6:4\]/);assert.match(node('linked-body').innerHTML,/<summary>已配置 · uid \/ Example<\/summary>/);
    const click=()=>node('linked-body').onclick({target:{closest:s=>s.includes('link-detail')?{dataset:{linkDetail:'0',linkSource:'0'},disabled:false}:null}});
    click();assert.equal(api.sheet().name,'ADDR_MAP');assert.equal(m.location.address,'B10');assert.equal(m.draft.size,0);
    api.returnToFlow();api.editCell({dataset:{edit:'S4'},value:'0.801'});click();assert.equal(api.sheet().name,'FLOW');
  });

  await test('delivery guidance follows readiness and retains saved snapshot path after edits',async()=>{
    const {api,m,node,context,reply}=setup();
    context.fetch=async()=>reply({valid:true,checkId:'ready',diagnostics:[]});await api.check();
    assert.match(node('delivery-status').textContent,/选择.*目标/);
    m.selectedTargets.add(state.targets[0].id);await api.check();
    assert.match(node('delivery-status').textContent,/可以生成/);
    assert.equal(node('delivery-save').disabled,false);
    context.fetch=async()=>reply({path:'review/copy.xlsx'});await api.save();
    assert.match(node('delivery-saved').textContent,/review\/copy.xlsx/);
    api.editCell({dataset:{edit:'S4'},value:'0.801'});
    assert.match(node('delivery-status').textContent,/检查/);
    assert.match(node('delivery-saved').textContent,/后续改动尚未保存/);
    assert.equal(node('delivery-save').disabled,true);
    const output=api.renderJobResult({outputs:[{path:'one',file_count:3},{error:'bad'}]});
    assert.match(output,/成功 1.*失败 1/);
  });

  await test('review workflow keeps pending navigation and compares only completed same-scope checks',async()=>{
    const {api,m,node,context,reply}=setup();
    const a={severity:'ERROR',code:'A',message:'first',provenance:{sheet:'FLOW',coordinate:'S4'}},b={severity:'WARN',code:'B',message:'second',provenance:{sheet:'FLOW',coordinate:'B5'}};
    context.fetch=async()=>reply({valid:false,diagnostics:[a,b]});await api.check();
    assert.match(node('review-scope').textContent,/整本.*所有 CP/);
    assert.match(node('review-progress').textContent,/1 个错误.*1 个提醒/);
    node('issue-first').onclick();assert.equal(m.selectedRow,4);
    api.editCell({dataset:{edit:'S4'},value:'0.801'});
    node('issue-next').onclick();assert.equal(m.selectedRow,5);assert.equal(m.location,null);
    assert.match(node('review-progress').textContent,/待复查/);
    context.fetch=async()=>reply({valid:false,diagnostics:[b]});await api.check();
    assert.match(node('review-progress').textContent,/已解决 1/);
    m.flowOrder=[3,2];api.editCell({dataset:{edit:'S4'},value:'0.802'});
    assert.equal(node('issue-first').disabled,true);
    context.fetch=async()=>reply({valid:true,diagnostics:[]});await api.check();
    assert.match(node('review-progress').textContent,/可另存.*生成/);
  });

  await test('all reference workbook columns have sheet-specific guidance without creating edits',()=>{
    const headers={"VERSION": ["CP num", "product name", "Program Name", "tester", "read bit", "program bit", "page word", "bank", "CLK PIN", "SWD PIN", "NRST PIN", "GET PIN", "pdr min", "pdr target", "pdr max", "vcc min", "vcc typ", "vcc max", "erase time(ms)", "program time(ms)", "VTE target", "VTP target", "VTE bake target", "VTP bake target", "CP spec", "CP ver high", "CP ver low", "project name", "project ver", "vpose", "vnege", "vposp", "vnegp"], "FLOW": ["CP NO", "item", "relay", "sub", "type", "Recipe", "OTP", "UID", "PUMP", "mode", "DAC bit", "step", "LINE", "Bisection", "PE", "FV/FI", "meas pin", "low_range(%)", "target", "high_range(%)", "UNIT", "Hbin", "Sbin", "Vcc", ""], "ADDR_MAP": ["Word No.", "CPU Address", "SM Address", "Contents", "line", "bit[31:16]", "bit[15:0]", "data type", "CP Data[31:0]", "description", "CP addr map", "备注"], "PIN DEC": ["CP NO", "Pad No.:", "X [um]", "Y [um]", "Trace", "Con", "E/C(Pad Name)", "Site"], "KP RELAY": ["F0 Channel", "KP RELAY F0", "F1 Channel", "KP RELAY F1"], "NM_pattern": ["No", "used", "Pattern name"], "FLASH_EPR": ["addr", "configs", "Description", "mode", "opr_mode", "opr_value", "space", "page_num", "chessboard_mode", "chessboard_data", "fbist_mode", "fbist_cmd", "comp_flag", "comp_data", "ecc"], "pattern": ["item", "addr", "description", "pattern"], "PIN DEC SINGEL": ["TESTER", "Pad No.:", "Trace", "E/C(Pad Name)", "Site"], "IOMUX": ["pin", "analog / ADC", "DAC", "COMP", "OPA", "VREF", "test / SCAN", "fbist", "additional / wakeup", "other"], "OPA": ["mode", "inp0_force", "inp1_force", "inn0_force", "inn1_force", "down_limit", "target", "up_limit", "step"], "PVD": ["case", "up/down", "min", "typ", "max", "limit", "expect", "step"], "DAC": ["mode", "code", "down_limit", "up_limit", "step"], "ADC": ["ADC", "Chanel", "force", "limit", "step"], "FREQ": ["FREQ", "source", "mul", "div", "down_limit", "up_limit", "step"]};
    const {api,m,node}=setup();
    for(const [name,labels] of Object.entries(headers)){
      m.state.sheets.push({name,maxRow:3,maxCol:labels.length,columns:labels.map(label=>({label})),rows:Array.from({length:3},()=>labels.map(()=>({value:null,editable:true})))});
      m.sheetIndex=m.state.sheets.length-1;
      for(let c=0;c<labels.length;c++){
        let n=c+1,address='';while(n){n--;address=String.fromCharCode(65+n%26)+address;n=Math.floor(n/26);}
        api.selectGridCell(address+'3');
        assert.doesNotMatch(node('field-hint').textContent,/暂未提供|尚未收录/,name+' '+labels[c]);
        assert.ok(node('field-hint').textContent.length>8,name+' '+labels[c]);
      }
    }
    assert.equal(m.draft.size,0);
  });

  await test('LINE and OPA guidance uses confirmed field meanings without changing drafts',()=>{
    const {api,m,node}=setup(),flow=m.state.sheets[m.sheetIndex];
    flow.columns[12].label='LINE';api.selectGridCell('M4');
    assert.match(node('field-hint').textContent,/yes.*连续码.*no.*自定义码/);
    assert.doesNotMatch(node('field-hint').textContent,/BOR|多行/);
    m.state.sheets.push({name:'OPA',maxRow:2,maxCol:4,columns:['inp0_force','inp1_force','inn0_force','inn1_force'].map(label=>({label})),rows:Array.from({length:2},()=>Array.from({length:4},()=>({value:null,editable:true})))});
    m.sheetIndex=m.state.sheets.length-1;
    for(const [address,meaning] of [['A2','P 为正端'],['B2','P 为正端'],['C2','N 为负端'],['D2','N 为负端']]){
      api.selectGridCell(address);assert.ok(node('field-hint').textContent.includes(meaning));
      assert.doesNotMatch(node('field-hint').textContent,/两个|PT104|暂未提供/);
    }
    assert.equal(m.draft.size,0);
  });
  await test('FLOW field guidance follows selection and reports current, stale and cleared diagnostics',()=>{
    const {api,m,node}=setup(),flow=m.state.sheets[m.sheetIndex];flow.columns[18].label='target';flow.columns[20].label='UNIT';flow.columns[20].choices=['V','mV'];
    api.selectGridCell('S4');assert.match(node('field-title').textContent,/FLOW!S4.*target/);assert.match(node('field-hint').textContent,/UNIT/);
    api.renderDiagnostics([{severity:'ERROR',provenance:{sheet:'FLOW',coordinate:'S4'},message:'目标不合法',remediation:'填写数值'}, {severity:'WARN',provenance:{sheet:'FLOW',coordinate:'row 4'},message:'行级提醒'}]);
    api.renderTable();assert.match(node('table-host').innerHTML,/field-mark error/);assert.match(node('field-issues').innerHTML,/目标不合法/);assert.match(node('field-issues').innerHTML,/行级提醒/);
    api.editCell({dataset:{edit:'S4'},value:'0.801'});api.renderTable();
    assert.doesNotMatch(node('table-host').innerHTML,/field-mark error/);assert.match(node('field-state').textContent,/待重新检查/);assert.doesNotMatch(node('field-issues').innerHTML,/目标不合法/);
    api.renderDiagnostics([]);assert.match(node('field-state').textContent,/不代表完整检查通过/);
    api.selectGridCell('U4');assert.match(node('field-hint').textContent,/V.*mV/);assert.equal(m.draft.size,1);
  });
  await test('diagnostic markers distinguish row provenance and never survive FLOW reorder',()=>{
    const {api,m,node}=setup(),flow=m.state.sheets[m.sheetIndex];
    for(const [r,item] of [[2,'A'],[3,'B']]){flow.rows[r-1][0].value='CP1';flow.rows[r-1][1].value=item;}
    api.renderDiagnostics([{severity:'ERROR',provenance:{sheet:'FLOW',coordinate:'$S$2'},message:'cell'}, {severity:'WARN',provenance:{sheet:'FLOW',coordinate:'row 3'},message:'whole row'}, {severity:'ERROR',provenance:{sheet:'WORKBOOK'},message:'global'}]);
    api.selectGridCell('S3');assert.match(node('field-issues').innerHTML,/整行.*whole row/);assert.doesNotMatch(node('field-issues').innerHTML,/global/);
    api.moveFlowGroup(2,3,true);assert.doesNotMatch(node('table-host').innerHTML,/field-mark (error|warn)/);assert.match(node('field-state').textContent,/待重新检查/);
  });
  await test('Recipe blur errors stay local, clear after repair, and ignore late responses',async()=>{
    const {api,m,node,context,reply}=setup();m.state.sheets[m.sheetIndex].columns[5].label='Recipe';
    context.fetch=async()=>reply({text:'',source:'default',steps:[{module:'ENTER',arguments:''}],error:'',manual:[{name:'ENTER',description:'进入配置',parameters:['WAIT：非负整数 + US/MS'],example:'ENTER(WAIT=1MS)'}]});
    await api.openRecipe(4);
    const field={dataset:{recipeField:'arguments',index:'0'},value:'WAIT=bad'},event={target:{closest:()=>field}};
    node('recipe-table').input(event);
    context.fetch=async()=>reply({error:'WAIT必须带单位',issues:[{index:0,message:'WAIT必须带单位'}],warnings:[]});
    await node('recipe-table').focusout(event);
    assert.match(node('recipe-feedback-0').textContent,/错误.*WAIT/);assert.equal(m.draft.size,0);
    assert.equal(m.recipe.steps[0].arguments,'WAIT=bad');
    let finish;context.fetch=()=>new Promise(resolve=>finish=resolve);
    const pending=node('recipe-table').focusout(event);
    field.value='WAIT=1MS';node('recipe-table').input(event);
    finish(reply({error:'旧错误',issues:[{index:0,message:'旧错误'}]}));await pending;
    assert.doesNotMatch(node('recipe-feedback-0').textContent,/旧错误/);
    context.fetch=async()=>reply({error:'',issues:[],warnings:[]});await node('recipe-table').focusout(event);
    assert.equal(node('recipe-feedback-0').textContent,'');assert.equal(m.draft.size,0);
    assert.match(node('recipe-hint-0').textContent,/WAIT/);
  });
  await test('Recipe apply focuses invalid arguments and raw repair cannot edit stale module rows',async()=>{
    const {api,m,node,context,reply}=setup();m.state.sheets[m.sheetIndex].columns[5].label='Recipe';
    context.fetch=async()=>reply({text:'',source:'default',steps:[{module:'RUN',arguments:''}],error:'',manual:[]});
    await api.openRecipe(4);
    node('recipe-table').input({target:{closest:()=>({dataset:{recipeField:'arguments',index:'0'},value:'123'})}});
    let focused=false;context.document.querySelector=()=>({focus(){focused=true;}});
    context.fetch=async()=>reply({error:'RUN名称非法',issues:[{index:0,message:'RUN名称非法'}],warnings:[]});
    await api.applyRecipe();assert.equal(focused,true);assert.equal(m.draft.size,0);assert.equal(m.recipe.steps[0].arguments,'123');
    node('recipe-raw').value='RUN(';node('recipe-raw').oninput();
    assert.equal(node('recipe-error').textContent,'');
    context.fetch=async()=>reply({error:'括号不完整',issues:[{index:null,message:'括号不完整'}],warnings:[]});
    await api.applyRecipe();assert.equal(node('recipe-raw-details').open,true);assert.equal(m.recipe.raw,'RUN(');
    assert.match(node('recipe-table').innerHTML,/<input[^>]*data-recipe-field="arguments"[^>]*disabled/);assert.equal(m.draft.size,0);
  });
  await test('FLOW drag moves whole items, keeps edits attached and restores order through undo and storage',()=>{
    const {api,m,node}=setup(),flow=m.state.sheets[m.sheetIndex];
    flow.columns[0].label='CP NO';flow.columns[1].label='item';
    for(const [r,cp,item] of [[2,'CP1','Alpha'],[3,'CP1','Alpha'],[4,'CP1','Beta'],[5,'CP2','Other']]){flow.rows[r-1][0].value=cp;flow.rows[r-1][1].value=item;flow.rows[r-1][4].value='verify';}
    api.editCell({dataset:{edit:'S2'},value:'123'});api.moveFlowGroup(2,4,true);
    assert.deepEqual(Array.from(m.flowOrder).slice(0,5),[1,4,2,3,5]);
    assert.equal(api.sheet().rows[1][1].value,'Beta');assert.equal(api.sheet().rows[2][1].value,'Alpha');
    api.editCell({dataset:{edit:'T3'},value:'456'});
    assert.ok(api.changes().some(x=>x.cell==='S2'&&x.value==='123'));
    assert.ok(api.changes().some(x=>x.cell==='T2'&&x.value==='456'));
    api.saveDraft();m.flowOrder=[];m.draft.clear();api.restoreDraft();
    assert.deepEqual(Array.from(m.flowOrder).slice(0,4),[1,4,2,3]);
    assert.equal(m.draft.get('FLOW!T2').value,'456');
    assert.throws(()=>api.moveFlowGroup(3,5),/CP/);
    m.recipe={modified:true};assert.throws(()=>api.moveFlowGroup(3,2),/Recipe/);m.recipe=null;
    api.moveFlowGroup(3,2);assert.equal(m.flowOrder.length,0);
    node('undo-btn').onclick();assert.deepEqual(Array.from(m.flowOrder).slice(0,4),[1,4,2,3]);
  });
  await test('FLOW drag distinguishes same-name types and copying after a move uses the displayed source',()=>{
    const {api,m}=setup(),flow=m.state.sheets[m.sheetIndex];
    for(const [r,item,type] of [[2,'Alpha','trim'],[3,'Beta','trim'],[4,'Alpha','verify']]){flow.rows[r-1][0].value='CP1';flow.rows[r-1][1].value=item;flow.rows[r-1][4].value=type;}
    api.moveFlowGroup(2,3,true);assert.equal(api.sheet().rows[1][1].value,'Beta');assert.equal(api.sheet().rows[3][4].value,'verify');
    m.selectedRow=2;api.addRow(true);assert.equal(m.appendRows[0].sourceRow,3);
    assert.equal(m.flowOrder.length,flow.maxRow+1);assert.equal(api.sheet().maxRow,flow.maxRow+1);
    assert.match(api.changes().find(x=>x.cell==='B'+(flow.maxRow+1)).value,/Beta_Copy/);
    m.query='Alpha';assert.throws(()=>api.moveFlowGroup(2,3),/搜索/);
  });
  await test('FLOW pure-order check and save bind the order and later moves expire the check',async()=>{
    const {api,m,context,reply,node}=setup(),flow=m.state.sheets[m.sheetIndex];
    for(const [r,item] of [[2,'Alpha'],[3,'Beta'],[4,'Gamma']]){flow.rows[r-1][0].value='CP1';flow.rows[r-1][1].value=item;}
    api.moveFlowGroup(2,3,true);const sent=[];
    context.fetch=async(url,options)=>{sent.push([url,JSON.parse(options.body)]);return reply(url==='/api/check'?{valid:true,checkId:'ordered',targets:[],diagnostics:[]}: {path:'ordered.xlsx'});};
    await api.check();await api.save();assert.equal(sent.length,2);
    assert.deepEqual(sent[0][1].flowOrder,sent[1][1].flowOrder);assert.deepEqual(sent[1][1].flowOrder.slice(0,4),[1,3,2,4]);
    api.moveFlowGroup(3,4,true);assert.equal(m.check,null);assert.equal(node('save-btn').disabled,true);
  });
  await test('dragging a Recipe module inserts it at the target boundary without separating parameters',()=>{
    const {api,m}=setup();m.recipe={editable:true,pending:false,steps:[{module:'ENTER',arguments:'WAIT=1MS'},{module:'TRIM',arguments:''},{module:'JUDGE',arguments:'PF=NO'}],raw:'',baseValue:'',source:'default',version:0,manual:[],selected:0};
    api.moveRecipeModule(0,3);assert.deepEqual(Array.from(m.recipe.steps,s=>s.module),['TRIM','JUDGE','ENTER']);
    assert.equal(m.recipe.steps[2].arguments,'WAIT=1MS');assert.equal(m.recipe.raw,'TRIM-JUDGE(PF=NO)-ENTER(WAIT=1MS)');assert.equal(m.draft.size,0);
    const version=m.recipe.version;api.moveRecipeModule(2,3);assert.equal(m.recipe.version,version);
    m.recipe.editable=false;api.moveRecipeModule(2,0);assert.equal(m.recipe.steps[2].module,'ENTER');
  });
  await test('Recipe page reuses code pane and presents expandable help categories',async()=>{
    const {api,m,node,context,reply}=setup();m.state.sheets[m.sheetIndex].columns[5].label='Recipe';
    const pane=node('code-pane');node('inspector').appendChild(pane);pane.hidden=true;
    node('item-code').value='existing preview';
    context.fetch=async()=>reply({text:'',source:'default',defaultText:'ENTER-TRIM-JUDGE',steps:[{module:'ENTER',arguments:''}],error:'',manual:[{name:'ENTER',description:'进入配置',parameters:[],example:'ENTER'},{name:'SRAM_CAPTURE',description:'读取数据',parameters:[],example:'SRAM_CAPTURE(0x100,2x16)'}]});
    await api.openRecipe(4);
    assert.equal(pane.parentElement,node('recipe-code-slot'));assert.equal(pane.hidden,false);
    assert.match(node('recipe-help-list').innerHTML,/<details[^>]*data-help-group/);
    assert.match(node('recipe-help-list').innerHTML,/<summary>.*进入与校准/);
    assert.match(node('recipe-help-list').innerHTML,/采集与结果/);
    assert.doesNotMatch(html,/id="recipe-help-search"/);
    assert.equal(m.linkRow,4);
    node('recipe-return').onclick();assert.equal(pane.parentElement,node('inspector'));assert.equal(pane.hidden,true);
  });
  await test('blank Recipe displays gray default modules without writing them to the draft',async()=>{
    const {api,m,node,context,reply}=setup();m.state.sheets[m.sheetIndex].columns[5].label='Recipe';
    const styles=new Map();node('recipe-table').classList.toggle=(name,on)=>styles.set(name,on);
    context.fetch=async()=>reply({text:'',source:'default',defaultText:'ENTER-TRIM-JUDGE',steps:[{module:'ENTER',arguments:''},{module:'TRIM',arguments:''},{module:'JUDGE',arguments:''}],error:'',manual:[]});
    await api.openRecipe(4);assert.equal(styles.get('recipe-default'),true);assert.equal(node('recipe-default-badge').hidden,false);
    assert.match(node('recipe-table').innerHTML,/ENTER/);assert.match(node('recipe-table').innerHTML,/TRIM/);assert.match(node('recipe-table').innerHTML,/JUDGE/);assert.equal(m.draft.size,0);
    node('recipe-table').input({target:{closest:()=>({dataset:{recipeField:'arguments',index:'0'},value:'WAIT=1MS'})}});
    assert.equal(styles.get('recipe-default'),false);assert.equal(node('recipe-default-badge').hidden,true);assert.equal(m.draft.size,0);
  });
  await test('Recipe button opens its exact FLOW row, applies once and undo restores it',async()=>{
    const {api,m,node,context,reply}=setup();m.state.sheets[m.sheetIndex].columns[5].label='Recipe';
    api.renderTable();assert.match(node('table-host').innerHTML,/data-recipe="F4"/);
    assert.doesNotMatch(node('table-host').innerHTML,/<input[^>]*data-edit="F4"/);
    context.fetch=async(url,options)=>{assert.equal(url,'/api/recipe');const p=JSON.parse(options.body);return reply({text:p.text,source:p.text?'explicit':'default',defaultText:'ENTER-TRIM-JUDGE',steps:[{module:'ENTER',arguments:''},{module:'TRIM',arguments:''},{module:'JUDGE',arguments:''}],error:'',manual:[]});};
    await api.openRecipe(4);assert.equal(m.recipe.row,4);assert.equal(m.recipe.address,'F4');assert.equal(m.draft.size,0);
    assert.equal(node('recipe-page').hidden,false);assert.equal(node('editor-page').hidden,true);
    m.recipe.raw='RUN(foo)-JUDGE';m.recipe.modified=true;await api.applyRecipe();
    assert.equal(m.draft.get('FLOW!F4').value,'RUN(foo)-JUDGE');assert.equal(m.undo.length,1);
    node('undo-btn').onclick();assert.equal(m.draft.size,0);
  });
  await test('Recipe syntax errors and concurrent cell changes never overwrite the draft',async()=>{
    const {api,m,context,reply}=setup();m.state.sheets[m.sheetIndex].columns[5].label='Recipe';
    context.fetch=async(url,options)=>reply({text:JSON.parse(options.body).text,source:'explicit',steps:[],defaultText:'',error:'bad recipe',manual:[]});
    await api.openRecipe(4);m.recipe.raw='BAD(';m.recipe.modified=true;await api.applyRecipe();assert.equal(m.draft.size,0);
    m.recipe.raw='JUDGE';api.editCell({dataset:{edit:'F4'},value:'TRIM'});
    context.fetch=async()=>reply({text:'JUDGE',source:'explicit',steps:[{module:'JUDGE',arguments:''}],error:'',manual:[]});
    await api.applyRecipe();assert.equal(m.draft.get('FLOW!F4').value,'TRIM');
  });
  await test('Recipe apply refuses a renamed item and preserves the local buffer',async()=>{
    const {api,m,context,reply}=setup(),flow=m.state.sheets[m.sheetIndex];
    flow.columns[5].label='Recipe';flow.columns[1].label='item';flow.rows[3][1].value='original_item';
    context.fetch=async()=>reply({text:'',source:'blank',steps:[],defaultText:'',error:'',manual:[]});
    await api.openRecipe(4);m.recipe.raw='TRIM';m.recipe.modified=true;
    api.editCell({dataset:{edit:'B4'},value:'another_item'});await api.applyRecipe();
    assert.equal(m.draft.has('FLOW!F4'),false);assert.equal(m.recipe.raw,'TRIM');assert.match(m.recipe.error,/item.*变化/);
  });
  await test('fixed columns render selects preserving historical values and read-only protection',()=>{
    const {api,m,node}=setup();m.columnMode='all';
    m.state.sheets[m.sheetIndex].columns[18].choices=['','no','yes','/'];
    api.renderTable();const markup=node('table-host').innerHTML;
    assert.match(markup,/<select[^>]*data-edit="S4"/);
    assert.match(markup,/<option value="0.8" selected>0.8（原有值）<\/option>/);
    assert.match(markup,/<option value="yes">yes<\/option>/);
    assert.match(markup,/<input[^>]*data-edit="T4"/);
    m.state.sheets[m.sheetIndex].rows[3][18].editable=false;api.renderTable();
    assert.doesNotMatch(node('table-host').innerHTML,/<select[^>]*data-edit="S4"/);
  });
  await test('select mouse and keyboard keep native opening while changes support undo',()=>{
    const {api,m,node,handlers}=setup();api.selectGridCell('S4');
    const td={dataset:{cell:'S4'}},target={tagName:'SELECT',dataset:{edit:'S4'},value:'yes',matches:()=>true,closest:selector=>selector==='[data-cell]'?td:null};
    let prevented=false;node('table-host').mousedown({target,button:0,preventDefault(){prevented=true;}});
    assert.equal(prevented,false);
    handlers.keydown({target,key:'ArrowDown',preventDefault(){prevented=true;}});assert.equal(prevented,false);
    handlers.focusin({target});handlers.input({target});handlers.change({target});
    assert.equal(m.draft.get('FLOW!S4').value,'yes');assert.equal(m.undo.length,1);
    node('undo-btn').onclick();assert.equal(m.draft.size,0);
  });
  await test('double clicking a size boundary fits visible content without changing the draft',()=>{
    const {api,m,node,context}=setup();
    context.getComputedStyle=()=>({paddingLeft:'4',paddingRight:'4',paddingTop:'3',paddingBottom:'3'});
    context.document.body={appendChild(){}};
    context.document.createElement=()=>({style:{},textContent:'',remove(){},getBoundingClientRect(){return {width:this.textContent.length*10,height:this.textContent.split('\n').length*20};}});
    const input={value:'a'.repeat(30)+'\nsecond\nthird',matches:()=>true,getBoundingClientRect:()=>({width:160})};
    context.document.querySelectorAll=()=>[{dataset:{cell:'S4'},querySelector:()=>input}];
    const before=JSON.stringify(api.snapshot()),revision=m.revision;
    const handle={dataset:{resizeAxis:'column',resizeIndex:'19'}};
    node('table-host').dblclick({target:{closest:()=>handle},preventDefault(){}});
    assert.ok(api.gridDimension('column',19)>300);
    handle.dataset.resizeAxis='row';handle.dataset.resizeIndex='4';node('table-host').dblclick({target:{closest:()=>handle},preventDefault(){}});
    assert.equal(api.gridDimension('row',4),69);
    assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(m.revision,revision);assert.equal(m.undo.length,0);
  });
  await test('row heights and column widths persist across section renders without changing workbook data',()=>{
    const {api,m,node}=setup();groupedFlow(m);api.selectSheetSection(m.sheetIndex,'CP1');
    const before=JSON.stringify(api.snapshot()),revision=m.revision;
    api.setGridDimension('column',19,280);api.setGridDimension('row',4,90);
    api.selectSheetSection(m.sheetIndex,'CP2');api.selectSheetSection(m.sheetIndex,'CP1');
    assert.equal(api.gridDimension('column',19),280);assert.equal(api.gridDimension('row',4),90);
    assert.match(node('table-host').innerHTML,/data-size-column="19" style="width:280px"/);
    assert.match(node('table-host').innerHTML,/--row-height:90px/);
    assert.match(node('table-host').innerHTML,/<tr data-excel-row="4"[^>]*class="[^"]*sized-row/);
    assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(m.revision,revision);assert.equal(m.undo.length,0);
    m.state.sha256='another-workbook';assert.ok(api.gridDimension('column',19)<160);assert.equal(api.gridDimension('row',4),null);
  });
  await test('cell resizing clamps dimensions and reset restores automatic row sizing',()=>{
    const {api}=setup();api.setGridDimension('column',19,1);assert.equal(api.gridDimension('column',19),72);
    api.setGridDimension('row',4,9999);assert.equal(api.gridDimension('row',4),480);
    api.setGridDimension('row',4,null);assert.equal(api.gridDimension('row',4),null);
    assert.throws(()=>api.setGridDimension('row',0,90),/尺寸/);
    assert.throws(()=>api.setGridDimension('column',19,NaN),/尺寸/);
  });
  await test('Excel selection follows visible cells, copies TSV and fills atomically',async()=>{
    const {api,m,node}=setup();m.columnMode='all';
    api.selectGridCell('S4');api.selectGridCell('T6',true);
    assert.equal(api.gridSelection().rows.length,3);assert.equal(api.gridSelection().cols.length,2);
    api.editCell({dataset:{edit:'T4'},value:'hello\t"world"\nnext'});
    const text=api.copyGridText();assert.ok(text.includes('"hello\t""world""\nnext"'));
    assert.equal(api.parseGridText(text)[0][1],'hello\t"world"\nnext');
    api.changeGridRange('down');assert.equal(m.draft.get('FLOW!S6').value,'0.8');
    node('undo-btn').onclick();assert.ok(!m.draft.has('FLOW!S6'));
    api.selectGridCell('S4');api.selectGridCell('T6',true);
    m.state.sheets[m.sheetIndex].rows[5][19].formula='=1';
    const before=JSON.stringify(api.snapshot());assert.throws(()=>api.changeGridRange('clear'),/只读|公式/);
    assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('Excel movement uses visible rows and columns without leaving the section',async()=>{
    const {api,m}=setup();m.columns.set('FLOW',new Set([1,19,21]));
    assert.equal(api.gridMoveAddress('S4','ArrowRight'),'U4');
    assert.equal(api.gridMoveAddress('U4','Tab'),'A5');
    assert.equal(api.gridMoveAddress('A5','Tab',true),'U4');
    api.editCell({dataset:{edit:'S4'},value:'unique_navigation_fixture'});
    m.query='unique_navigation_fixture';assert.equal(api.gridMoveAddress('S4','Enter'),'S4');
    assert.throws(()=>api.parseGridText('"unterminated'),/引号/);
  });
  await test('leaving an unchanged CP cell does not schedule a focus-destroying render',async()=>{
    const {api,m,handlers}=setup();groupedFlow(m);api.selectSheetSection(m.sheetIndex,'CP1');
    const input={dataset:{edit:'A4'},value:'CP1',matches:()=>true};
    handlers.focusin({target:input});handlers.blur({target:input});assert.equal(m.sectionTimer,null);
  });
  function groupedFlow(m){
    const s=m.state.sheets.find(s=>s.name==='FLOW');s.headerRows=1;s.columns[0].label='CP NO';
    s.maxRow=125;s.rows=Array.from({length:125},(_,r)=>Array.from({length:s.maxCol},(_,c)=>({value:r===0?'header':c===0?(r<=65?'CP1':'CP2'):null,editable:r>0})));
    s.appendableRows=Array.from({length:124},(_,i)=>i+2);return s;
  }
  await test('CP navigation shows all section rows and keeps original coordinates and drafts',async()=>{
    const {api,m,node}=setup();groupedFlow(m);api.selectSheetSection(m.sheetIndex,'CP1');
    assert.equal(api.filteredRows(api.sheet()).length,65);assert.ok(node('table-host').innerHTML.includes('data-edit="S66"'));
    assert.ok(!node('table-host').innerHTML.includes('data-edit="S67"'));assert.equal(node('pagination-controls').hidden,true);
    api.editCell({dataset:{edit:'S66'},value:'0.802'});api.selectSheetSection(m.sheetIndex,'CP2');
    assert.ok(node('table-host').innerHTML.includes('data-edit="S125"'));assert.equal(m.draft.get('FLOW!S66').value,'0.802');
    m.query='CP1';assert.equal(api.filteredRows(api.sheet()).length,0);m.query='';
    api.renderDiagnostics([{severity:'ERROR',message:'bad',provenance:{sheet:'FLOW',coordinate:'S66'}}]);api.locateDiagnostic(0);
    assert.equal(m.section,'CP1');assert.equal(m.location.address,'S66');assert.equal(m.draft.size,1);
  });
  await test('editing CP moves its row and undo returns to the original section',async()=>{
    const {api,m,node,handlers,runTimer}=setup();m.columnMode='all';groupedFlow(m);api.selectSheetSection(m.sheetIndex,'CP1');
    const input={dataset:{edit:'A4'},value:'CP1',matches:()=>true};handlers.focusin({target:input});input.value='CP2';handlers.input({target:input});handlers.blur({target:input});
    await runTimer(m.sectionTimer);assert.equal(m.section,'CP2');assert.ok(node('table-host').innerHTML.includes('data-edit="A4"'));
    node('undo-btn').onclick();assert.equal(m.section,'CP1');assert.ok(node('table-host').innerHTML.includes('data-edit="A4"'));
  });
  await test('section paste and batch cannot touch hidden CP rows, append inherits selected CP',async()=>{
    const {api,m,node}=setup();groupedFlow(m);api.selectSheetSection(m.sheetIndex,'CP1');
    api.pasteValues({dataset:{edit:'S65'}},'1\n2');assert.equal(m.draft.get('FLOW!S66').value,'2');
    const before=JSON.stringify(api.snapshot());assert.throws(()=>api.pasteValues({dataset:{edit:'S66'}},'1\n2'),/分区|范围/);assert.equal(JSON.stringify(api.snapshot()),before);
    m.selectedRow=66;m.selectedColumn=19;api.openBatchFill();node('batch-start').value='66';node('batch-end').value='67';node('batch-value').value='3';
    assert.throws(()=>api.previewBatchFill(),/分区/);assert.equal(JSON.stringify(api.snapshot()),before);
    api.addRow(false);assert.equal(m.draft.get('FLOW!A126').value,'CP1');assert.equal(m.section,'CP1');assert.ok(node('table-host').innerHTML.includes('data-edit="S126"'));
  });
  await test('explicit section fields handle merged continuation, missing values and unclassified sheets',async()=>{
    const {api,m}=setup();
    const adc={name:'ADC',headerRows:1,maxRow:5,maxCol:2,columns:[{label:'ADC'},{label:'Chanel'}],rows:[[{value:'ADC'},{value:'Chanel'}],[{value:'ADC1'},{value:0}],[{value:null,reason:'合并单元格的从格，请编辑主格'},{value:1}],[{value:'ADC2'},{value:0}],[{value:null,editable:true},{value:2}]]};
    m.state.sheets.push(adc);let groups=api.sheetSections(adc);assert.deepEqual(JSON.parse(JSON.stringify(groups.map(g=>[g.value,g.rows]))),[['ADC1',[2,3]],['ADC2',[4]],['',[5]]]);
    const pattern={...adc,name:'pattern',columns:[{label:'item'},{label:'description'}],rows:[[{value:'item'},{value:'description'}],[{value:'A'},{value:'one'}],[{value:null},{value:'two'}],[{value:'B'},{value:'three'}],[{value:null},{value:'four'}]]};
    assert.deepEqual(JSON.parse(JSON.stringify(api.sheetSections(pattern).map(g=>g.rows))),[[2,3],[4,5]]);
    assert.equal(api.sheetSections({...adc,name:'IOMUX',columns:[{label:'PIN'},{label:'ADC'}]}).length,0);
  });
  await test('finishing the first cell edit enables undo immediately',async()=>{
    const {api,m,node,handlers}=setup();
    const input={dataset:{edit:'S4'},value:'0.8',matches:()=>true};
    handlers.focusin({target:input});input.value='0.809';handlers.input({target:input});handlers.blur({target:input});
    assert.equal(m.undo.length,1);assert.equal(node('undo-btn').disabled,false);
    node('undo-btn').onclick();assert.equal(m.draft.size,0);
  });
  await test('workspace switching preserves edits and diagnostics return to editor',async()=>{
    const {api,m,node}=setup();
    api.editCell({dataset:{edit:'S4'},value:'0.809'});
    const before=JSON.stringify(api.snapshot()),revision=m.revision;
    node('workspace-build').onclick();assert.equal(node('editor-page').hidden,true);assert.equal(node('build-page').hidden,false);
    node('workspace-review').onclick();assert.equal(node('review-page').hidden,false);
    api.renderDiagnostics([{severity:'ERROR',message:'test',provenance:{sheet:'FLOW',coordinate:'S4'}}]);
    api.locateDiagnostic(0);assert.equal(node('editor-page').hidden,false);
    assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(m.revision,revision);
    node('inspector-links').onclick();assert.equal(node('code-pane').hidden,true);assert.equal(node('links-pane').hidden,false);
    node('inspector-toggle').onclick();assert.equal(node('inspector').hidden,true);
    node('inspector-code').onclick();assert.equal(node('inspector').hidden,false);assert.equal(node('code-pane').hidden,false);
  });
  await test('desktop preview opens separately, clears on edits and restores inline when closed',async()=>{
    const {api,m,node,context,handlers,reply,runTimer}=setup();let opened=0;const snapshots=[];
    context.window.pywebview={api:{publish_preview:async v=>snapshots.push(v),set_busy:async()=>{},open_preview:async()=>{opened++;}}};
    assert.ok(handlers.pywebviewready,'desktop bridge ready handler');handlers.pywebviewready();
    assert.equal(node('item-detach').hidden,false);
    context.fetch=async()=>reply({valid:true,item:'Live',cp:'CP1',rows:[4],recipe:['ENTER'],text:'void live() {}'});
    m.selectedRow=4;api.renderLinks();await runTimer(m.itemTimer);
    await node('item-detach').onclick();assert.equal(opened,1);assert.equal(node('item-inline').hidden,true);
    assert.equal(snapshots.at(-1).code,'void live() {}');
    api.editCell({dataset:{edit:'S4'},value:'0.801'});assert.equal(snapshots.at(-1).code,'');
    assert.ok(snapshots.every((s,i)=>!i||s.sequence>snapshots[i-1].sequence));
    context.window.desktopPreviewClosed();assert.equal(node('item-inline').hidden,false);
    context.window.pywebview.api.open_preview=async()=>{throw Error('native failure');};
    await node('item-detach').onclick();assert.equal(node('item-inline').hidden,false);
  });
  await test('live item preview automatically follows selection, edits and platform without checking',async()=>{
    const {api,m,node,context,reply,runTimer}=setup();const calls=[];
    context.fetch=async(url,options)=>{calls.push([url,JSON.parse(options.body)]);return reply({valid:true,item:'Live',cp:'CP1',rows:[4],recipe:['ENTER','JUDGE'],text:'void live() {}'});};
    m.selectedRow=4;api.renderLinks();assert.ok(m.itemTimer);await runTimer(m.itemTimer);
    assert.equal(node('item-code').value,'void live() {}');assert.equal(m.check,null);assert.equal(m.jobId,null);
    api.editCell({dataset:{edit:'S4'},value:'0.801'});assert.equal(node('item-code').value,'');await runTimer(m.itemTimer);
    assert.equal(calls.at(-1)[1].changes[0].value,'0.801');assert.equal(calls.at(-1)[0],'/api/item-preview');
    node('item-platform').onchange({target:{value:'s100'}});await runTimer(m.itemTimer);assert.equal(calls.at(-1)[1].platform,'s100');
    m.selectedRow=5;api.renderLinks();await runTimer(m.itemTimer);assert.equal(calls.at(-1)[1].row,5);
    m.selectedRow=4;api.renderLinks();api.editCell({dataset:{edit:'S4'},value:'0.802'});const latest=m.itemTimer;
    api.editCell({dataset:{edit:'S4'},value:'0.803'});assert.notEqual(m.itemTimer,latest);await runTimer(m.itemTimer);
    assert.equal(calls.at(-1)[1].changes[0].value,'0.803');
  });
  await test('live item preview drops stale requests, coalesces edits and clears invalid code',async()=>{
    const {api,m,node,context,reply,runTimer}=setup();let done,calls=0;
    context.fetch=()=>{calls++;return new Promise(resolve=>{done=resolve;});};
    m.selectedRow=4;api.renderLinks();const pending=runTimer(m.itemTimer);
    api.editCell({dataset:{edit:'S4'},value:'0.805'});api.editCell({dataset:{edit:'S4'},value:'0.806'});assert.equal(calls,1);
    done(reply({valid:true,text:'OLD'}));await pending;assert.equal(node('item-code').value,'');assert.ok(m.itemTimer);
    context.fetch=async()=>reply({valid:false,text:'',diagnostics:[{message:'missing module',provenance:{sheet:'FLOW',coordinate:'S4'}}]});await runTimer(m.itemTimer);
    assert.equal(node('item-code').value,'');assert.match(node('item-errors').innerHTML,/missing module/);assert.match(node('item-errors').innerHTML,/FLOW/);
    context.fetch=async()=>{throw Error('offline');};node('item-retry').onclick();await runTimer(m.itemTimer);assert.match(node('item-status').textContent,/offline/);
    assert.equal(m.itemInFlight,false);assert.equal(m.busy,false);assert.equal(m.check,null);
  });
  await test('pre-generation preview needs a check and shows selected target code without a job',async()=>{
    const {api,m,node,context,reply}=setup();const targets=m.state.targets.map(t=>t.id);m.selectedTargets=new Set(targets);
    let calls=[];context.fetch=async(url,options)=>{calls.push(url);return reply(url==='/api/preview'?{previewId:'p',target:JSON.parse(options.body).target,inputSha256:'draft-sha',files:[{path:'main.pln',size:20,previewable:true}],releaseBlockers:['STUB']}:{text:'void draft() {}',encoding:'utf-8'});};
    await node('preview-btn').onclick();assert.equal(calls.length,0);
    m.check={revision:m.revision,scope:'program',result:{valid:true,checkId:'c'}};
    await node('preview-btn').onclick();assert.equal(node('output-code').value,'void draft() {}');assert.equal(m.jobId,null);
    assert.match(node('output-meta').textContent,/draft-sha/);assert.match(node('output-note').textContent,/未写入/);
    assert.match(node('output-blockers').innerHTML,/STUB/);assert.ok(node('preview-target').innerHTML.includes(targets[1]));
    await node('preview-target').onchange({target:{value:targets[1]}});assert.equal(m.outputView.target,targets[1]);
    assert.ok(calls.every(url=>url.startsWith('/api/preview')));
    api.editCell({dataset:{edit:'S4'},value:'0.802'});assert.equal(node('output-dialog').open,false);assert.equal(node('preview-btn').disabled,true);
  });
  await test('pre-generation preview ignores late results after edits or close and clears failed content',async()=>{
    const {api,m,node,context,reply}=setup();m.selectedTargets=new Set([m.state.targets[0].id]);
    m.check={revision:m.revision,scope:'program',result:{valid:true,checkId:'c'}};
    let done;context.fetch=()=>new Promise(resolve=>{done=resolve;});
    const pending=node('preview-btn').onclick();api.editCell({dataset:{edit:'S4'},value:'0.803'});
    done(reply({previewId:'late',files:[{path:'old.pln',previewable:true}]}));await pending;
    assert.equal(node('output-code').value,'');assert.equal(m.busy,false);
    m.check={revision:m.revision,scope:'program',result:{valid:true,checkId:'d'}};
    const closed=node('preview-btn').onclick();node('output-dialog').close();done(reply({previewId:'closed',files:[]}));await closed;
    assert.equal(m.outputView.previewId,undefined);
    context.fetch=async()=>({ok:false,status:422,json:async()=>({error:'预览构建失败'})});
    await node('preview-btn').onclick();assert.equal(node('output-code').value,'');assert.match(node('output-meta').textContent,/预览构建失败/);
  });
  await test('Pattern description uses multiline input and Enter/paste retain cell content',()=>{
    const {api,m,node,handlers}=linkSetup();m.sheetIndex=m.state.sheets.findIndex(s=>s.name==='pattern');
    m.state.sheets[m.sheetIndex].columns[2].label='description';m.state.sheets[m.sheetIndex].rows[1][2].value='0,LOW=01\n2,HIGH=10*';
    api.renderTable();assert.match(node('table-host').innerHTML,/<textarea[^>]*data-edit="C2"[^>]*>0,LOW=01\n2,HIGH=10\*<\/textarea>/);
    m.cellEditing=true;let prevented=false;const target={tagName:'TEXTAREA',matches:()=>true,dataset:{edit:'C2'},closest:()=>({dataset:{cell:'C2'}}),blur(){}};
    handlers.keydown({target,key:'Enter',preventDefault(){prevented=true;}});assert.equal(prevented,false);
    handlers.paste({target,clipboardData:{getData:()=> '0,LOW=11\n2,HIGH=00*'},preventDefault(){prevented=true;}});assert.equal(prevented,false);
    handlers.keydown({target,key:'Enter',ctrlKey:true,preventDefault(){prevented=true;}});assert.equal(prevented,true);
  });
  await test('VERSION shows all fields in wrapped CP sections and retains cell draft identity',()=>{
    const {api,m,node}=linkSetup();
    m.state.sheets[0]={...m.state.sheets[1],name:'VERSION',columns:m.state.sheets[1].columns.map((c,i)=>({...c,label:i===0?'CP num':(c.label||'Field '+i)}))};
    m.sheetIndex=0;m.section='CP1';m.columnMode='common';
    assert.equal(api.selectedColumns(api.sheet()).length,api.sheet().maxCol);
    api.renderTable();assert.match(node('table-host').innerHTML,/version-fields/);
    assert.match(node('table-host').innerHTML,/data-edit="X4"/);
    const before=api.snapshot();api.editCell({dataset:{edit:'X4'},value:'version-value'});api.commitBefore(before);
    assert.ok(api.changes().some(x=>x.sheet==='VERSION'&&x.cell==='X4'&&x.value==='version-value'));
    node('undo-btn').onclick();assert.equal(m.draft.size,0);
  });
  await test('linked preview shows register fields before a clear jump button',()=>{
    const {api,m,node}=linkSetup();m.state.links[0].patterns[0].preview=[{address:'0010010',data:'0000000000000011',fields:[{name:'DAC<3:0>',high:3,low:0,value:'0011',dynamic:true}]}];
    api.renderLinks();const html=node('linked-body').innerHTML;
    for(const text of ['0010010','DAC&lt;3:0&gt;','0011','动态默认值','跳到配置表'])assert.ok(html.includes(text));
    assert.ok(html.indexOf('DAC&lt;3:0&gt;')<html.indexOf('跳到配置表'));assert.doesNotMatch(html,/>pattern!Y55<\/button>/);
  });
  function linkSetup(){
    const env=setup(),{m}=env;
    m.state.sheets=m.state.sheets.filter(s=>s.name!=='pattern');m.state.sheets.push({name:'pattern',maxRow:60,maxCol:25,columns:Array.from({length:25},(_,i)=>({label:String(i)})),rows:Array.from({length:60},()=>Array.from({length:25},()=>({value:'config',editable:true,formula:null})))});
    m.state.links=[{flowRow:4,cp:'CP1',item:'TRIM',patterns:[{name:'enter_real',uses:['ENTER'],locations:[{sheet:'pattern',coordinate:'Y55'}],note:''},{name:'unmapped',uses:['RUN'],locations:[],note:'no source'}]}];m.selectedRow=4;
    return env;
  }
  await test('VERIFY offers Pattern mapping even before links have compiled',()=>{
    const {api,m,node}=mappingSetup();
    m.selectedRow=5;m.state.links=[];
    api.renderLinks();
    assert.match(node('linked-body').innerHTML,/data-trim-pattern[^>]*>编辑 Pattern 映射/);
    assert.doesNotMatch(node('linked-body').innerHTML,/流程映射/);
  });
  await test('specialized associations show source cards without an empty storage branch and keep stale guards',()=>{
    const {api,m,node}=linkSetup();
    for(const kind of ['OPA_TEST','DAC_TEST','FREQ_TEST','ADC_TEST','VERIFY_HEX','VERIFY_KEIL','DC_PARAMETRIC_TEST','DC_VIH_VIL']){
      Object.assign(m.state.links[0],{kind,specialized:true,patterns:[],details:[{title:'配置与步骤',text:'PA0 → HL < SRAM',locations:[{sheet:'FLOW',coordinate:'S55',label:'查看阶段'}]}]});
      api.renderLinks();const html=node('linked-body').innerHTML;
      assert.match(html,/配置与步骤/);assert.match(html,/HL &lt; SRAM/);
      assert.doesNotMatch(html,/ADDR MAP|暂无已识别 Pattern|data-storage-map/);
    }
    const click=()=>node('linked-body').onclick({target:{closest:s=>s.includes('link-detail')?{dataset:{linkDetail:'0',linkSource:'0'},disabled:false}:null}});
    click();assert.equal(m.location.address,'S55');
    m.selectedRow=4;api.renderLinks();api.editCell({dataset:{edit:'S4'},value:'changed'});api.renderLinks();
    assert.match(node('linked-body').innerHTML,/关联已过期/);click();assert.equal(m.selectedRow,4);
  });
  await test('external resource slots expose concrete SWD Link choices without mutating the program draft',()=>{
    const {api,m,node}=linkSetup();
    Object.assign(m.state.links[0],{kind:'ADC_TEST',specialized:true,patterns:[],resourceSlots:[{phase:'ADC1',role:'config',label:'配置 Pattern',status:'placeholder',configurable:false,names:{shared:['PT104_SWD_ADC1','<external>']}}]});
    const before=JSON.stringify(api.snapshot());api.renderLinks();const html=node('linked-body').innerHTML;
    for(const text of ['ADC1','点击选择结果','PT104_SWD_ADC1','&lt;external&gt;','data-resource-link="PT104_SWD_ADC1"'])assert.ok(html.includes(text),text);
    assert.doesNotMatch(html,/data-pattern-link/);assert.doesNotMatch(html,/data-swd-link|data-scan-link/);assert.doesNotMatch(html,/data-resource-save|已绑定/);assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('generated patterns do not duplicate configuration cards and retain actual test configuration',()=>{
    const {api,m,node}=linkSetup();m.state.links[0].kind='MAIN';
    m.state.links[0].resourceSlots=[{phase:'RUN',role:'pattern',label:'执行 Pattern',status:'generated',names:{shared:['enter_real']}}];
    m.state.links[0].details=[{title:'ADDR_MAP 存储映射',summary:'已配置 · trim1 / FIELD',text:'真实存储配置',locations:[]}];
    const before=JSON.stringify(api.snapshot());api.renderLinks();
    assert.doesNotMatch(node('linked-body').innerHTML,/配置（预留）/);
    assert.match(node('linked-body').innerHTML,/本工具生成/);
    assert.doesNotMatch(node('linked-body').innerHTML,/生成配置|跳到配置表/);
    const markup=node('linked-body').innerHTML;
    assert.ok(markup.indexOf('data-link-column="storage"') < markup.indexOf('data-link-column="patterns"'));
    assert.match(markup,/<section[^>]*data-link-column="storage"/);
    const right=markup.split('data-link-column="storage"')[1].split('data-link-column="patterns"')[0];
    assert.match(right,/真实存储配置/);
    assert.doesNotMatch(right,/enter_real/);
    const left=node('linked-body').innerHTML.split('data-link-column="patterns"')[1].split('data-link-column="configuration"')[0];
    assert.match(left,/data-link-pattern="0"/);assert.match(left,/pattern!Y55/);
    assert.match(left,/class="pattern-card-main"[^>]*data-fbist-link="0"/);
    assert.match(left,/>编辑源表<\/button>/);
    assert.doesNotMatch(node('linked-body').innerHTML,/占位 · 外部工具尚未接入/);
    assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('HEX resource card displays its saved source and opens that resource directly',()=>{
    const {api,m,node}=linkSetup();
    Object.assign(m.state.links[0],{kind:'CODE_DOWNLOAD',patterns:[],resourceSlots:[{phase:'DOWNLOAD',role:'download',status:'placeholder',label:'固件下载',names:{shared:['firmware']}}]});
    m.patternLibrary={links:[{target:{cp:'CP1',names:{shared:['firmware']}},generationId:'g'}],generations:[{id:'g',sourceKind:'hex',pattern:'raw',stale:false,files:[{platform:'chroma'},{platform:'s100'}],source:{name:'HSI.hex',profile:{chip:'PT104',label:'Flash'}}}]};
    api.renderLinks();const html=node('linked-body').innerHTML;
    for(const value of ['HSI.hex','PT104','已关联','data-resource-link="firmware"'])assert.ok(html.includes(value),value);
    assert.doesNotMatch(html,/data-resource-link="firmware"[^>]*disabled/);
    m.patternLibrary.links[0].target.cp='CP2';api.renderLinks();assert.doesNotMatch(node('linked-body').innerHTML,/HSI.hex/);
    m.patternLibrary.links[0].target.cp='CP1';m.patternLibrary.sha256='different-workbook';api.renderLinks();assert.doesNotMatch(node('linked-body').innerHTML,/HSI.hex/);
  });
  await test('shared SWD target opens from later FLOW row without crossing CP or item',()=>{
    const {api,m}=linkSetup();const item=m.state.links[0];m.linkRow=item.flowRow;
    const target={row:197,cp:item.cp,item:item.item,names:{shared:['PT104_SWD_ADC1']}};
    assert.equal(api.patternTargetMatches(target,m.linkRow,'PT104_SWD_ADC1'),true);
    assert.equal(api.patternTargetMatches({...target,cp:'different'},m.linkRow,'PT104_SWD_ADC1'),false);
    assert.equal(api.patternTargetMatches({...target,item:'different'},m.linkRow,'PT104_SWD_ADC1'),false);
    assert.equal(api.patternTargetMatches(target,m.linkRow,'removed_pattern'),false);
    assert.equal(api.patternTargetMatches(target,999,'PT104_SWD_ADC1'),false);
  });
  await test('SWD resource links saved steps before any generation exists',()=>{
    const {api,m,node}=linkSetup();
    Object.assign(m.state.links[0],{kind:'SWD_TEST',patterns:[],resourceSlots:[{role:'config',status:'placeholder',names:{shared:['required_pattern']}}]});
    m.patternLibrary={links:[{target:{cp:'CP1',names:{shared:['required_pattern']}},swdSource:{documentId:'doc',pattern:'source_steps'}}],generations:[],sources:[{id:'source:1',documentId:'doc',pattern:'source_steps',sourceKind:'swd',sourceLabel:'program.xlsx',files:[{platform:'chroma'},{platform:'s100'}]}]};
    api.renderLinks();const html=node('linked-body').innerHTML;
    for(const value of ['required_pattern','source_steps','生成程序时自动生成','已关联'])assert.ok(html.includes(value),value);
    m.patternLibrary.sources=[];api.renderLinks();assert.match(node('linked-body').innerHTML,/步骤来源已删除/);
  });
  await test('SWD picker offers direct XLSX import and document scoped source filtering',()=>{
    assert.match(html,/data-swd-upload/);
    assert.match(html,/data-document-filter/);
    assert.match(source,/\/api\/swd\/import/);
    assert.match(source,/X-File-Name/);
    assert.match(source,/\/api\/pattern\/state/);
    assert.match(source,/documentId/);
    assert.match(source,/sourceLabel/);
  });
  await test('generated slots without a Pattern table location never open an external link',()=>{
    const {api,m,node}=linkSetup();Object.assign(m.state.links[0],{patterns:[],resourceSlots:[{status:'generated',names:{shared:['page_read']}}]});
    api.renderLinks();assert.match(node('linked-body').innerHTML,/page_read/);assert.doesNotMatch(node('linked-body').innerHTML,/data-resource-link="page_read"/);
  });
  await test('HEX and SWD VERIFY rows expose resource cards, never the ordinary FBIST mapping editor',()=>{
    const {api,m,node}=linkSetup(),flow=m.state.sheets.find(s=>s.name==='FLOW');
    flow.columns[0].label='CP NO';flow.columns[1].label='item';flow.columns[4].label='type';flow.columns[9].label='mode';
    flow.rows[3][0].value='CP1';flow.rows[3][1].value='firmware';flow.rows[3][4].value='verify';
    for(const mode of ['hex','swd','scan','mbist']){
      flow.rows[3][9].value=mode;Object.assign(m.state.links[0],{kind:'VERIFY_HEX',patterns:[],resourceSlots:[{role:'download',status:'placeholder',names:{shared:['firmware']}}]});
      api.renderLinks();assert.doesNotMatch(node('linked-body').innerHTML,/data-trim-pattern|data-storage-map/);
    }
  });
  await test('association layout keeps resources and configuration without the execution sequence',()=>{
    const {api,m,node}=linkSetup();
    Object.assign(m.state.links[0],{specialized:true,kind:'ADC_TEST',patterns:[],
      resourceSlots:[{phase:'ADC1',role:'config',label:'配置',status:'placeholder',names:{shared:['CONFIG_ONE']}}],
      details:[{title:'ADC 专表配置',text:'配置摘要',locations:[]}],
      stages:[{label:'采集',patterns:['CONFIG_ONE'],details:[0]}]});
    api.renderLinks();const html=node('linked-body').innerHTML;
    assert.doesNotMatch(html,/link-sequence|data-link-stage="|点击上方阶段/);
    const left=html.split('data-link-column="patterns"')[1].split('data-link-column="configuration"')[0];
    assert.match(left,/CONFIG_ONE/);assert.doesNotMatch(left,/配置摘要/);
    assert.match(html.split('data-link-column="configuration"')[1],/配置摘要/);
    assert.match(html,/data-link-stages="0"/);
    assert.doesNotMatch(html,/ADDR MAP/);
    let rewrites=0,markup=html;
    Object.defineProperty(node('linked-body'),'innerHTML',{get(){return markup;},set(value){markup=value;rewrites++;}});
    api.renderLinks();assert.equal(rewrites,0,'unchanged blur refresh must preserve the pending click target');
    assert.equal(node('linked-body').innerHTML,html);
  });
  await test('module details preview values and navigate sources with stale protection',()=>{
    const {api,m,node}=linkSetup();m.state.links[0].kind='DAC_ADJUST';
    m.state.links[0].details=[{title:'DAC_ADJ',text:'RAW < 0.4; DAC +2',locations:[{sheet:'FLOW',coordinate:'S55',label:'条件配置'}]}];
    api.renderLinks();assert.match(node('linked-body').innerHTML,/RAW &lt; 0.4/);
    const click=()=>node('linked-body').onclick({target:{closest:selector=>selector.includes('link-detail')?{dataset:{linkDetail:'0',linkSource:'0'},disabled:false}:null}});
    const before=JSON.stringify(api.snapshot());click();assert.equal(m.location.address,'S55');assert.equal(JSON.stringify(api.snapshot()),before);
    m.selectedRow=4;api.renderLinks();api.editCell({dataset:{edit:'S4'},value:'0.9'});click();assert.equal(m.selectedRow,4);
  });
  await test('shared usage shows VERIFY and navigates its FLOW row without edits',()=>{
    const {api,m,node}=linkSetup();
    m.state.links.push({flowRow:55,cp:'CP2',kind:'VERIFY',item:'Shared_VERIFY',patterns:[m.state.links[0].patterns[0]],unexpanded:['SETVPOSP']});
    const before=JSON.stringify(api.snapshot());api.renderLinks();
    assert.match(node('linked-body').innerHTML,/已识别引用（2行）/);
    assert.match(node('linked-body').innerHTML,/Shared_VERIFY/);
    node('linked-body').onclick({target:{closest:selector=>selector.includes('link-user')?{dataset:{linkPattern:'0',linkUser:'55'},disabled:false}:null}});
    assert.equal(m.selectedRow,55);assert.equal(m.page,m.section===null?1:0);assert.equal(m.linkRow,55);
    assert.match(node('linked-body').innerHTML,/尚未展开.*SETVPOSP/);
    api.followLink(0,0);assert.equal(m.location.address,'Y55');api.returnToFlow();assert.equal(m.selectedRow,55);
    assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('shared usage refuses stale links and unreferenced FLOW rows',()=>{
    const {api,m,node}=linkSetup();api.renderLinks();
    const click=row=>node('linked-body').onclick({target:{closest:selector=>selector.includes('link-user')?{dataset:{linkPattern:'0',linkUser:String(row)},disabled:false}:null}});
    click(56);assert.equal(m.selectedRow,4);
    m.state.links.push({flowRow:55,cp:'CP2',kind:'VERIFY',item:'Shared_VERIFY',patterns:[m.state.links[0].patterns[0]]});
    api.editCell({dataset:{edit:'S4'},value:'0.9'});click(55);
    assert.equal(m.selectedRow,4);assert.match(node('linked-body').innerHTML,/关联已过期/);
    assert.ok((node('linked-body').innerHTML.match(/<button[^>]*data-link-user="55"[^>]*>/g)||[]).every(button=>/\bdisabled\b/.test(button)));
  });
  await test('trim panel follows exact Pattern cell, reveals column and returns without edits',()=>{
    const {api,m,node}=linkSetup();const before=JSON.stringify(api.snapshot());api.renderLinks();assert.match(node('linked-body').innerHTML,/enter_real/);
    api.followLink(0,0);assert.equal(api.sheet().name,'pattern');assert.equal(m.page,1);assert.equal(m.location.address,'Y55');assert.ok(api.selectedColumns(api.sheet()).includes(25));
    api.returnToFlow();assert.equal(api.sheet().name,'FLOW');assert.equal(m.selectedRow,4);assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('changed Pattern disables old links and a current check supplies new coordinates',async()=>{
    const {api,m,node,context,reply}=linkSetup();api.renderLinks();api.followLink(0,0);api.editCell({dataset:{edit:'Y55'},value:'new config'});
    assert.match(node('linked-body').innerHTML,/关联已过期/);api.returnToFlow();api.followLink(0,0);assert.equal(api.sheet().name,'FLOW');
    context.fetch=async()=>reply({valid:true,checkId:'updated',diagnostics:[],links:[{...m.state.links[0],patterns:[{name:'updated',uses:['ENTER'],locations:[{sheet:'pattern',coordinate:'B8'}]}]}]});
    await api.check();api.followLink(0,0);assert.equal(m.location.address,'B8');assert.equal(api.changes().length,1);
  });
  await test('unsupported rows and unlocated resources do not invent links',()=>{
    const {api,m,node}=linkSetup();api.renderLinks();api.followLink(1,0);assert.equal(api.sheet().name,'FLOW');
    m.selectedRow=5;api.renderLinks();assert.match(node('linked-body').innerHTML,/普通 TRIM/);assert.doesNotMatch(node('linked-body').innerHTML,/data-link-pattern/);
  });
  function batchSetup(){
    const env=setup(),{m,api,node}=env;
    m.state.sheets.push({name:'BATCH',maxRow:1101,maxCol:3,columns:[{label:'ID'},{label:'value'},{label:'protected'}],
      rows:Array.from({length:1101},(_,r)=>Array.from({length:3},(_,c)=>({value:'old-'+r,editable:r>0&&c!==2,formula:c===2?'=1':null})))});
    m.sheetIndex=m.state.sheets.length-1;m.selectedRow=49;api.openBatchFill();
    node('batch-column').value='2';node('batch-start').value='49';node('batch-end').value='52';node('batch-value').value='0012';node('batch-mode').value='value';
    return env;
  }
  await test('batch fill previews across pages, commits once and supports undo redo',()=>{
    const {api,m,node}=batchSetup();const before=JSON.stringify(api.snapshot());api.previewBatchFill();
    assert.equal(JSON.stringify(api.snapshot()),before);assert.match(node('batch-preview').innerHTML,/B52/);
    api.applyBatchFill();assert.equal(m.undo.length,1);assert.equal(api.changes().length,4);assert.ok(api.changes().every(c=>c.value==='0012'));
    node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);node('redo-btn').onclick();assert.equal(api.changes().length,4);
  });
  await test('batch fill rejects protected, invalid, filtered and oversized ranges atomically',()=>{
    for(const values of [{column:'3'},{start:'1'},{start:'52',end:'49'},{start:'2.5'},{end:'1200'},{start:'2',end:'1002'},{value:'=SUM(A1)'},{query:'filter'}]){
      const {api,m,node}=batchSetup(),before=JSON.stringify(api.snapshot());
      for(const [k,v] of Object.entries(values))if(k==='query')m.query=v;else node('batch-'+k).value=v;
      assert.throws(()=>api.previewBatchFill());assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(m.batchPlan,null);
    }
  });
  await test('protected cell in the middle never leaves a partial batch',()=>{
    const {api,m,node}=batchSetup();m.state.sheets[m.sheetIndex].rows[50][1].editable=false;
    const before=JSON.stringify(api.snapshot());assert.throws(()=>api.previewBatchFill(),/B51/);assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('batch fill supports draft appended rows and undo keeps those rows',()=>{
    const {api,m,node}=setup();m.selectedRow=4;api.addRow(true);api.addRow(false);
    const last=api.sheet().maxRow,before=JSON.stringify(api.snapshot());api.openBatchFill();node('batch-column').value='2';node('batch-start').value=String(last-1);node('batch-end').value=String(last);node('batch-value').value='Batch_Added';node('batch-mode').value='value';
    api.previewBatchFill();api.applyBatchFill();assert.equal(m.appendRows.length,2);assert.equal(api.changes().filter(x=>x.value==='Batch_Added').length,2);
    node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('batch preview cannot apply after edits, form changes or closing',()=>{
    for(const action of ['edit','form','close']){
      const {api,m,node}=batchSetup();api.previewBatchFill();
      if(action==='edit')api.editCell({dataset:{edit:'B2'},value:'later'});
      if(action==='form')node('batch-value').value='changed';if(action==='close')node('batch-dialog').close();
      const before=JSON.stringify(api.snapshot());assert.throws(()=>api.applyBatchFill());assert.equal(JSON.stringify(api.snapshot()),before);
    }
  });
  await test('fill down uses current edited first value and blank fill is explicit',()=>{
    const {api,m,node}=batchSetup();api.editCell({dataset:{edit:'B49'},value:'-0.05'});node('batch-mode').value='down';
    api.previewBatchFill();api.applyBatchFill();assert.equal(api.changes().filter(c=>c.value==='-0.05').length,4);
    api.openBatchFill();node('batch-column').value='2';node('batch-start').value='49';node('batch-end').value='52';node('batch-mode').value='value';node('batch-value').value='';
    api.previewBatchFill();assert.match(node('batch-preview').innerHTML,/清空/);api.applyBatchFill();assert.ok(api.changes().every(c=>c.value===''));
    api.saveDraft();const before=JSON.stringify(api.snapshot());m.draft.clear();api.restoreDraft();assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('batch no-op does not add undo or invalidate checks',()=>{
    const {api,m,node}=batchSetup();node('batch-end').value='49';node('batch-value').value='old-48';
    api.previewBatchFill();const rev=m.revision;api.applyBatchFill();assert.equal(m.revision,rev);assert.equal(m.undo.length,0);
  });
  await test('output browser shows actual text, filters files and never changes draft',async()=>{
    const {api,m,node,context,reply}=setup();m.jobId='job';const before=JSON.stringify(api.snapshot());
    context.fetch=async url=>reply(url.includes('&file=')?{path:'main.pln',text:'void <unsafe>() {}\nGUI_Copy();',encoding:'utf-8',truncated:false}:{inputSha256:'generated-sha',files:[{path:'main.pln',size:30,previewable:true},{path:'binary.bin',size:4,previewable:false}]});
    await api.openOutput(0);await api.previewFile('main.pln');
    assert.equal(node('output-code').value,'void <unsafe>() {}\nGUI_Copy();');assert.match(node('output-meta').textContent,/generated-sha/);
    node('output-filter').value='main';node('output-filter').oninput();assert.doesNotMatch(node('output-files').innerHTML,/binary.bin/);
    node('code-query').value='gui_copy';node('output-code').setSelectionRange=(a,b)=>{node('output-code').selection=[a,b];};
    api.searchCode();assert.deepEqual(node('output-code').selection,[19,27]);
    assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(m.revision,0);
  });
  await test('late preview and closed dialogs cannot overwrite selected file',async()=>{
    const {api,m,node,context,reply}=setup();m.jobId='job';
    context.fetch=async()=>reply({inputSha256:'sha',files:[]});await api.openOutput(0);
    let done;context.fetch=()=>new Promise(resolve=>{done=resolve;});const old=api.previewFile('old.pln');
    context.fetch=async()=>reply({text:'NEW',encoding:'utf-8',truncated:true});await api.previewFile('new.pln');
    done(reply({text:'OLD',encoding:'utf-8'}));await old;assert.equal(node('output-code').value,'NEW');assert.match(node('output-file-status').textContent,/截断/);
    context.fetch=()=>new Promise(resolve=>{done=resolve;});const pending=api.previewFile('closed.pln');node('output-dialog').close();
    done(reply({text:'CLOSED',encoding:'utf-8'}));await pending;assert.notEqual(node('output-code').value,'CLOSED');
  });
  await test('preview error clears old code and reports a useful message',async()=>{
    const {api,m,node,context,reply}=setup();m.jobId='job';context.fetch=async()=>reply({inputSha256:'sha',files:[]});await api.openOutput(0);
    node('output-code').value='OLD';context.fetch=async()=>({ok:false,status:422,json:async()=>({error:'文件已删除'})});
    await api.previewFile('missing.pln');assert.equal(node('output-code').value,'');assert.match(node('output-file-status').textContent,/文件已删除/);
  });
  function mockGroup(){return {id:'test-definition',cp:'CP3',item:'SOURCE_GROUP',type:'verify',kind:'DC_PARAMETRIC_TEST',rows:[4,5],subs:['high','low'],recipe:['DC_TEST'],copyable:true,patterns:['CONFIG_PATTERN'],sharedSheets:['VERSION','PIN DEC'],notes:['shared facts']};}
  await test('copy dialog obtains checked canonical group from any member row',async()=>{
    const {api,m,context,reply,node}=setup();m.selectedRow=5;
    context.fetch=async()=>reply({valid:true,checkId:'group',diagnostics:[],targets:state.targets,groups:[mockGroup()]});
    await api.openGroupCopy();assert.equal(m.copyPlan.group.id,'test-definition');assert.ok(node('copy-group-dialog').open);
    assert.match(node('copy-group-body').innerHTML,/CONFIG_PATTERN/);assert.match(node('copy-group-body').innerHTML,/PIN DEC/);
  });
  await test('complete group copy is atomic, preserves edits and undoes in one step',async()=>{
    const {api,m,context,reply,node}=setup();m.selectedRow=5;api.editCell({dataset:{edit:'S4'},value:'0.812'});
    context.fetch=async()=>reply({valid:true,checkId:'group',diagnostics:[],targets:state.targets,groups:[mockGroup()]});
    await api.openGroupCopy();const before=JSON.stringify(api.snapshot()),last=api.sheet().maxRow;
    context.fetch=async()=>reply({valid:true,checkId:'copied',targets:state.targets,diagnostics:[],groups:[{...mockGroup(),item:'GUI_Group_Check',rows:[last+1,last+2]}]});
    await api.confirmGroupCopy('GUI_Group_Check');assert.deepEqual(Array.from(m.appendRows,x=>x.sourceRow),[4,5]);
    assert.equal(api.sheet().maxRow,last+2);
    for(const row of [last+1,last+2])assert.equal(api.changes().find(x=>x.cell==='B'+row).value,'GUI_Group_Check');
    assert.equal(api.changes().find(x=>x.cell==='S'+(last+1)).value,'0.812');
    assert.equal(m.check.result.checkId,'copied');node('undo-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
    node('redo-btn').onclick();assert.equal(m.appendRows.length,2);
  });
  await test('group copy rejects invalid names and stale or over-limit plans without partial rows',async()=>{
    const {api,m,context,reply}=setup();m.selectedRow=5;
    context.fetch=async()=>reply({valid:true,checkId:'group',diagnostics:[],targets:state.targets,groups:[mockGroup()]});
    await api.openGroupCopy();const before=JSON.stringify(api.snapshot());
    await assert.rejects(()=>api.confirmGroupCopy('bad name'));assert.equal(JSON.stringify(api.snapshot()),before);
    const plan=m.copyPlan;m.appendRows=Array.from({length:99},()=>({sheet:'FLOW',sourceRow:4,copy:true}));
    const full=JSON.stringify(api.snapshot());await assert.rejects(()=>api.confirmGroupCopy('GUI_Group_Check'));assert.equal(JSON.stringify(api.snapshot()),full);
    m.appendRows=[];m.copyPlan=plan;api.editCell({dataset:{edit:'S4'},value:'0.812'});
    await assert.rejects(()=>api.confirmGroupCopy('GUI_Group_Check'));assert.equal(m.appendRows.length,0);
  });
  await test('candidate validation rejects changed kind and preserves current edits on late response',async()=>{
    const {api,m,context,reply}=setup();m.selectedRow=5;
    context.fetch=async()=>reply({valid:true,checkId:'group',diagnostics:[],targets:state.targets,groups:[mockGroup()]});
    await api.openGroupCopy();const before=JSON.stringify(api.snapshot()),last=api.sheet().maxRow;
    context.fetch=async()=>reply({valid:true,checkId:'wrong',diagnostics:[],targets:state.targets,groups:[{...mockGroup(),item:'GUI_Group_Check',kind:'CHANGED_KIND',rows:[last+1,last+2]}]});
    await assert.rejects(()=>api.confirmGroupCopy('GUI_Group_Check'),/类型/);assert.equal(JSON.stringify(api.snapshot()),before);
    let done;context.fetch=()=>new Promise(resolve=>{done=resolve;});const pending=api.confirmGroupCopy('GUI_Group_Check');
    api.editCell({dataset:{edit:'S4'},value:'0.899'});
    done(reply({valid:true,checkId:'late',groups:[]}));await assert.rejects(()=>pending,/发生变化/);
    assert.equal(m.appendRows.length,0);assert.equal(api.changes().find(x=>x.cell==='S4').value,'0.899');
  });
  await test('closing the copy dialog cancels an in-flight candidate without adding rows',async()=>{
    const {api,m,context,reply,node}=setup();m.selectedRow=5;
    context.fetch=async()=>reply({valid:true,checkId:'group',diagnostics:[],groups:[mockGroup()]});await api.openGroupCopy();
    const before=JSON.stringify(api.snapshot()),last=api.sheet().maxRow;let done;
    context.fetch=()=>new Promise(resolve=>{done=resolve;});const pending=api.confirmGroupCopy('GUI_Group_Check');
    node('copy-group-dialog').close();done(reply({valid:true,checkId:'copied',groups:[{...mockGroup(),item:'GUI_Group_Check',rows:[last+1,last+2]}]}));
    await assert.rejects(()=>pending,/取消/);assert.equal(JSON.stringify(api.snapshot()),before);
  });
  if(state.diagnostics?.length)await test('real compiler diagnostics navigate to their actual provenance',()=>{
    const {api,m,node}=setup();
    for(const d of state.diagnostics){
      api.renderDiagnostics([d]);api.locateDiagnostic(0);const p=d.provenance||{};
      const cell=(p.coordinate||'').match(/^([A-Z]+)([1-9]\d*)$/),row=(p.coordinate||'').match(/^row ([1-9]\d*)$/);
      if(cell){assert.equal(api.sheet().name,p.sheet);assert.equal(m.location.address,p.coordinate);assert.match(node('table-host').innerHTML,/diagnostic-cell/);}
      else if(row){assert.equal(api.sheet().name,p.sheet);assert.equal(m.location.row,Number(row[1]));assert.equal(m.location.col,null);}
      else assert.equal(m.location,null);
    }
  });
  await test('diagnostic click switches sheet, clears search, reveals column and marks exact cell',()=>{
    const {api,m,node}=setup();m.sheetIndex=0;m.query='no matches';m.columns.set('FLOW',new Set([1]));
    api.renderDiagnostics([{severity:'WARN',provenance:{sheet:'FLOW',coordinate:'X55'},message:'test',remediation:'fix'}]);
    const before=JSON.stringify(api.snapshot()),rev=m.revision;
    node('diagnostics').onclick({target:{closest:()=>({dataset:{diagnostic:'0'}})}});
    assert.equal(api.sheet().name,'FLOW');assert.equal(m.query,'');assert.equal(m.page,m.section===null?1:0);
    assert.ok(api.selectedColumns(api.sheet()).includes(24));assert.equal(m.location.address,'X55');
    assert.match(node('table-host').innerHTML,/diagnostic-cell/);
    assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(m.revision,rev);
  });
  await test('row diagnostics can reach newly appended rows without inventing a column',()=>{
    const {api,m,node}=setup();m.selectedRow=4;api.addRow(true);const row=api.sheet().maxRow;
    api.renderDiagnostics([{severity:'ERROR',code:'COMPILER.RECIPE',provenance:{sheet:'FLOW',coordinate:'row '+row},message:"需要且只能 link 一个 pattern bundle，实际 0 个"}]);
    api.locateDiagnostic(0);assert.equal(m.location.row,row);assert.equal(m.location.col,null);
    assert.match(node('table-host').innerHTML,/diagnostic-row/);assert.match(node('diagnostics').innerHTML,/关联名称/);
  });
  await test('sheet-only and workbook-level diagnostics do not fabricate cell locations',()=>{
    const {api,m,node}=setup();api.renderDiagnostics([
      {provenance:{sheet:'FLOW',coordinate:''},message:'sheet error'},
      {provenance:{sheet:'WORKBOOK'},message:'workbook error'},
      {provenance:{sheet:'FLOW',coordinate:'A999999'},message:'outside snapshot'}]);
    api.locateDiagnostic(0);assert.equal(api.sheet().name,'FLOW');assert.equal(m.location,null);
    const before=m.sheetIndex;api.locateDiagnostic(1);assert.equal(m.sheetIndex,before);assert.equal(m.location,null);
    api.locateDiagnostic(2);assert.equal(m.location,null);assert.match(node('diagnostics').innerHTML,/超出/);
  });
  await test('edits invalidate diagnostic navigation and clearing removes old entries',()=>{
    const {api,m,node}=setup();api.renderDiagnostics([{provenance:{sheet:'FLOW',coordinate:'B55'},message:'old'}]);
    api.locateDiagnostic(0);api.editCell({dataset:{edit:'S4'},value:'0.801'});
    const page=m.page;api.locateDiagnostic(0);assert.equal(m.page,page);assert.equal(m.location,null);
    assert.match(node('diagnostics').innerHTML,/已过期/);assert.match(node('diagnostics').innerHTML,/待复查/);
    node('clear-diag').onclick();assert.equal(m.diagnostics.length,0);
  });
  await test('append copies current values, preserves base and supports undo redo',()=>{
    const {api,m,node}=setup();m.selectedRow=4;const oldCount=api.sheet().maxRow;
    api.editCell({dataset:{edit:'S4'},value:'0.812'});api.addRow(true);
    assert.equal(api.sheet().maxRow,oldCount+1);assert.equal(m.state.sheets[m.sheetIndex].maxRow,oldCount);
    assert.equal(api.changes().find(c=>c.cell==='S'+(oldCount+1)).value,'0.812');
    assert.equal(m.appendRows.length,1);assert.equal(m.check,null);
    node('undo-btn').onclick();assert.equal(api.sheet().maxRow,oldCount);
    node('redo-btn').onclick();assert.equal(api.sheet().maxRow,oldCount+1);
  });
  await test('new blank row and copied row survive draft recovery',()=>{
    const {api,m}=setup();m.selectedRow=4;api.addRow(false);api.saveDraft();
    const before=JSON.stringify(api.snapshot());m.appendRows=[];m.draft.clear();api.restoreDraft();
    assert.equal(JSON.stringify(api.snapshot()),before);
    assert.ok(api.sheet().rows.at(-1).every(c=>c.value===null));
  });
  await test('invalid restored append list leaves current draft unchanged',()=>{
    const {api,m,storage}=setup();m.selectedRow=4;api.addRow(true);const before=JSON.stringify(api.snapshot());
    const k='mcu-gui-draft:'+state.sha256,payload=JSON.parse(storage.get(k));payload.appendRows[0].sourceRow=1;
    storage.set(k,JSON.stringify(payload));assert.throws(()=>api.restoreDraft());
    assert.equal(JSON.stringify(api.snapshot()),before);
  });
  await test('checks and saves bind appended rows, not just cell edits',async()=>{
    const {api,m,context,reply}=setup();m.selectedRow=4;api.addRow(true);const submitted=[];
    context.fetch=async(_url,opts)=>{submitted.push(JSON.parse(opts.body));return reply({valid:true,checkId:'append',targets:state.targets,diagnostics:[],path:'copy.xlsx'});};
    await api.check();await api.save();assert.equal(submitted.length,2);
    for(const p of submitted)assert.deepEqual(p.appendRows,[{sheet:'FLOW',sourceRow:4,copy:true}]);
  });
  await test('paste is atomic at protected/hidden cells and is undoable',()=>{
    const {api,m,node}=setup(); const before=JSON.stringify(api.changes());
    assert.throws(()=>api.pasteValues({dataset:{edit:'S1'}},'1\t2'));
    assert.equal(JSON.stringify(api.changes()),before);
    api.pasteValues({dataset:{edit:'R4'}},'0.7\t0.801\t0.9');
    assert.equal(m.draft.size,3);assert.equal(m.undo.length,1);
    node('undo-btn').onclick();assert.equal(m.draft.size,0);
    node('redo-btn').onclick();assert.equal(m.draft.size,3);
  });
  await test('search follows newly edited values',()=>{
    const {api,m}=setup();api.editCell({dataset:{edit:'B4'},value:'GUI_UNIQUE_EDIT'});
    m.query='GUI_UNIQUE_EDIT';assert.deepEqual(Array.from(api.filteredRows(m.state.sheets[m.sheetIndex])),[4]);
  });
  await test('all columns overrides a prior custom selection',()=>{
    const {api,m,node}=setup();m.columns.set('FLOW',new Set([1]));
    node('column-mode').onchange({target:{value:'all'}});
    assert.equal(api.selectedColumns(m.state.sheets[m.sheetIndex]).length,m.state.sheets[m.sheetIndex].maxCol);
  });
  await test('storage failure never reports a successful draft save',()=>{
    const {api,context,node}=setup();context.localStorage.setItem=()=>{throw Error('quota');};
    assert.throws(()=>api.saveDraft());assert.doesNotMatch(node('global-message').textContent,/已按/);
  });
  await test('restore validates the whole draft before applying',()=>{
    const {api,m,storage}=setup();api.editCell({dataset:{edit:'S4'},value:'0.801'});
    const before=JSON.stringify(api.changes()), k='mcu-gui-draft:'+state.sha256;
    const draft=JSON.parse(storage.get(k));draft.changes.push({...draft.changes[0]});
    storage.set(k,JSON.stringify(draft));assert.throws(()=>api.restoreDraft());
    assert.equal(JSON.stringify(api.changes()),before);
  });
  await test('late check results cannot validate subsequent edits',async()=>{
    const {api,m,context,reply,node}=setup();let done;
    context.fetch=()=>new Promise(resolve=>{done=resolve;});const pending=api.check();
    api.editCell({dataset:{edit:'S4'},value:'0.801'});
    done(reply({valid:true,checkId:'stale',targets:state.targets,diagnostics:[]}));await pending;
    assert.equal(m.check,null);assert.equal(node('save-btn').disabled,true);
  });
  await test('checked targets update and removed selections are pruned',async()=>{
    const {api,m,context,reply}=setup();m.selectedTargets=new Set(state.targets.map(t=>t.id));
    context.fetch=async()=>reply({valid:true,checkId:'new',targets:state.targets.slice(0,1),diagnostics:[]});
    await api.check();assert.equal(m.state.targets.length,1);assert.equal(m.selectedTargets.size,1);
  });
  await test('save sends the exact checked edits',async()=>{
    const {api,m,context,reply}=setup();let body;
    api.editCell({dataset:{edit:'S4'},value:'0.801'});
    context.fetch=async()=>reply({valid:true,checkId:'checked',targets:state.targets,diagnostics:[]});await api.check();
    context.fetch=async(_url,opts)=>{body=JSON.parse(opts.body);return reply({path:'review/copy.xlsx'});};
    await api.save();assert.equal(body.checkId,'checked');assert.equal(body.baseSha256,state.sha256);
    assert.equal(body.changes[0].value,'0.801');
  });
  await test('draft Excel save binds submitted edits without granting check or discarding later changes',async()=>{
    const {api,m,node,context,reply}=setup();
    api.editCell({dataset:{edit:'S4'},value:'0.801'});let finish,sent;
    context.fetch=(url,opts)=>{assert.equal(url,'/api/save-draft');sent=JSON.parse(opts.body);return new Promise(resolve=>{finish=resolve;});};
    const pending=node('draft-file-btn').onclick();assert.equal(node('draft-file-btn').disabled,true);
    assert.equal(sent.checkId,undefined);assert.equal(sent.changes[0].value,'0.801');
    api.editCell({dataset:{edit:'S4'},value:'0.802'});
    finish(reply({path:'drafts/DRAFT_UNCHECKED_copy.xlsx',sha256:'saved',validation:'NOT_CHECKED'}));await pending;
    assert.equal(m.check,null);assert.equal(node('generate-btn').disabled,true);assert.equal(node('save-btn').disabled,true);
    assert.equal(api.changes()[0].value,'0.802');assert.equal(m.state.sha256,state.sha256);
    assert.match(node('global-message').textContent,/提交时快照/);assert.match(node('global-message').textContent,/未执行整本检查/);
  });
  await test('desktop save picker cancellation preserves draft and selected path is reported',async()=>{
    const {api,m,node,context}=setup();api.editCell({dataset:{edit:'S4'},value:'0.801'});
    const before=JSON.stringify(api.snapshot());let saved;
    context.window.pywebview={api:{publish_preview:async()=>{},set_busy:async()=>{},save_workbook:async()=>({cancelled:true})}};
    context.fetch=async()=>{throw Error('desktop save must use native picker');};
    await node('draft-file-btn').onclick();assert.equal(JSON.stringify(api.snapshot()),before);
    assert.match(node('global-message').textContent,/已取消/);assert.equal(m.lastSaved,null);
    context.window.pywebview.api.save_workbook=async(payload,checked)=>{saved=payload;assert.equal(checked,false);return {path:'D:/chosen/custom.xlsx',validation:'NOT_CHECKED'};};
    await node('draft-file-btn').onclick();assert.equal(saved.changes[0].value,'0.801');
    assert.equal(m.lastSaved.path,'D:/chosen/custom.xlsx');assert.equal(m.busy,false);
  });
  await test('checked desktop save uses the native picker with the checked snapshot',async()=>{
    const {api,m,context,reply}=setup();let saved;
    context.fetch=async()=>reply({valid:true,checkId:'checked',targets:state.targets,diagnostics:[]});await api.check();
    context.window.pywebview={api:{publish_preview:async()=>{},set_busy:async()=>{},save_workbook:async(payload,checked)=>{saved=payload;assert.equal(checked,true);return {path:'D:/chosen/checked.xlsx'};}}};
    await api.save();assert.equal(saved.checkId,'checked');assert.equal(m.lastSaved.path,'D:/chosen/checked.xlsx');
  });
  await test('draft Excel write failure keeps draft and does not report success',async()=>{
    const {api,m,node,context}=setup();api.editCell({dataset:{edit:'S4'},value:'0.801'});
    const before=JSON.stringify(api.snapshot());
    context.fetch=async()=>({ok:false,status:500,json:async()=>({error:'disk full'})});
    await node('draft-file-btn').onclick();
    assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(m.check,null);
    assert.match(node('global-message').textContent,/disk full/);assert.doesNotMatch(node('global-message').textContent,/已保存/);
    assert.equal(node('draft-file-btn').disabled,false);
  });
  await test('generation retry keeps the submitted revision',async()=>{
    const {api,m,context,reply,handlers,node}=setup();
    m.check={revision:m.revision,result:{valid:true,checkId:'ok'}};m.selectedTargets.add(state.targets[0].id);
    context.fetch=async url=>{if(url==='/api/generate')return reply({jobId:'job'});throw Error('offline');};
    await api.generate();await new Promise(resolve=>setImmediate(resolve));
    api.editCell({dataset:{edit:'S4'},value:'0.801'});
    context.fetch=async()=>reply({status:'completed',logs:[],result:{outputs:[],validation:{vendor_compiler_executed:false}}});
    handlers.click({target:{closest:selector=>selector==='#job-retry'?{}:null}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.match(node('global-message').textContent,/提交时快照/);
  });
  await test('output scope uses independent Pin targets and binds submitted scope',async()=>{
    const {api,m,node,context,reply}=setup();m.check={revision:m.revision,result:{valid:true,checkId:'ok'}};
    m.state.pinTargets=[{id:'pin-production',platform:'s100',cp:'CP3',variant:'production',name:'Pins'}];
    m.selectedTargets.add(state.targets[0].id);
    node('generation-scope').onchange({target:{value:'pin'}});
    assert.equal(m.selectedTargets.size,0);assert.match(node('targets').innerHTML,/pin-production/);
    assert.match(node('generation-note').textContent,/片段/);assert.match(node('generate-btn').textContent,/Pin/);
    assert.equal(m.check,null);assert.equal(node('generate-btn').disabled,true);
    m.selectedTargets.add('pin-production');let sent;
    context.fetch=async(_url,opts)=>{const p=JSON.parse(opts.body);assert.equal(p.scope,'pin');assert.deepEqual(p.targets,['pin-production']);return reply({valid:true,scope:'pin',checkId:'ok',checkedTargets:p.targets,pinTargets:m.state.pinTargets,diagnostics:[]});};
    await api.check();assert.equal(node('save-btn').disabled,true);assert.equal(node('generate-btn').disabled,false);
    context.fetch=async(url,opts)=>{if(url==='/api/generate'){sent=JSON.parse(opts.body);return reply({jobId:'pin-job'});}return reply({status:'completed',logs:[]});};
    await api.generate();assert.equal(sent.scope,'pin');assert.deepEqual(sent.targets,['pin-production']);
    assert.equal(sent.checkId,'ok');
    m.busy=false;node('generation-scope').onchange({target:{value:'program'}});assert.equal(m.check,null);assert.equal(node('generate-btn').disabled,true);
  });
  await test('result preserves partial failures, output paths and blockers',()=>{
    const {api}=setup();const output=api.renderJobResult({warnings:['warning'],validation:{vendor_compiler_executed:false},outputs:[
      {id:'good',path:'review/good',file_count:108,release_blockers:['STUB placeholder']},
      {id:'bad',error:'render failed',file_count:0,release_blockers:[]}]});
    for(const text of ['review/good','108','STUB placeholder','render failed','未厂商编译'])assert.ok(output.includes(text));
  });
  await test('ordinary FBIST check enables only scoped generation and expires on targets or edits',async()=>{
    const {api,m,node,context,reply}=setup();
    m.state.fbistTargets=[{id:'fbist-chroma',platform:'chroma'},{id:'fbist-s100',platform:'s100'}];
    node('generation-scope').onchange({target:{value:'fbist'}});
    assert.equal(m.generationScope,'fbist');assert.match(node('targets').innerHTML,/fbist-chroma/);
    assert.equal(node('check-btn').disabled,true);
    m.selectedTargets.add('fbist-chroma');let sent;
    context.fetch=async(url,opts)=>{sent=JSON.parse(opts.body);return reply({valid:true,scope:'fbist',checkId:'fbist-ok',checkedTargets:sent.targets,fbistTargets:m.state.fbistTargets,diagnostics:[]});};
    await api.check();assert.equal(sent.scope,'fbist');assert.equal(node('save-btn').disabled,true);assert.equal(node('generate-btn').disabled,false);
    context.fetch=async(url,opts)=>{if(url==='/api/generate'){sent=JSON.parse(opts.body);return reply({jobId:'fbist-job'});}return reply({status:'completed',logs:[]});};
    await api.generate();assert.equal(sent.scope,'fbist');assert.deepEqual(sent.targets,['fbist-chroma']);
    m.busy=false;node('targets').onclick({target:{closest:()=>({dataset:{target:'fbist-s100'},checked:true})}});
    assert.equal(m.check,null);assert.equal(node('generate-btn').disabled,true);
    context.fetch=async(url,opts)=>{const p=JSON.parse(opts.body);return reply({valid:true,scope:'fbist',checkId:'second',checkedTargets:p.targets,diagnostics:[]});};
    await api.check();api.editCell({dataset:{edit:'S4'},value:'0.802'});assert.equal(node('generate-btn').disabled,true);
    node('generation-scope').onchange({target:{value:'patterns'}});assert.equal(m.check,null);assert.equal(node('save-btn').disabled,true);
  });
  await test('loading a workbook starts at FLOW',async()=>{
    const {api,m,context,reply}=setup();context.fetch=async()=>reply(structuredClone(state));
    await api.loadFile({name:'copy.xlsx',arrayBuffer:async()=>new ArrayBuffer(0)});
    assert.equal(m.state.sheets[m.sheetIndex].name,'FLOW');
  });
  for(const [scope,field] of [['flash','flashTargets'],['flash_labels','flashLabelTargets'],['pump','pumpTargets']]) await test(scope+' scope binds platforms and expires when scope or selection changes',async()=>{
    const {api,m,node,context,reply}=setup();m.state[field]=[{id:'flash-chroma'},{id:'flash-s100'}];
    node('generation-scope').onchange({target:{value:scope}});
    assert.equal(m.generationScope,scope);assert.match(node('targets').innerHTML,/flash-chroma/);
    assert.equal(node('check-btn').disabled,true);m.selectedTargets.add('flash-chroma');let sent;
    context.fetch=async(url,opts)=>{sent=JSON.parse(opts.body);return reply({scope,valid:true,checkId:'flash-ok',checkedTargets:sent.targets,[field]:m.state[field],diagnostics:[]});};
    await api.check();assert.equal(sent.scope,scope);assert.equal(node('generate-btn').disabled,false);assert.equal(node('save-btn').disabled,true);
    node('targets').onclick({target:{closest:()=>({dataset:{target:'flash-s100'},checked:true})}});
    assert.equal(m.check,null);assert.equal(node('generate-btn').disabled,true);
    await api.check();assert.equal(node('generate-btn').disabled,false);
    node('generation-scope').onchange({target:{value:'fbist'}});assert.equal(m.check,null);assert.equal(node('generate-btn').disabled,true);
  });
  for(const [name,ok,error] of results)console.log((ok?'PASS ':'FAIL ')+name+(error?' — '+error:''));
  if(process.argv[3]&&results.every(x=>x[1])){
    state=integrationState;
    const {api,m,context,runTimer}=setup();
    if(process.argv[4]==='trim-pattern'){
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);const node=context.document.getElementById;
      m.selectedRow=12;api.renderLinks();
      await node('linked-body').onclick({target:{closest:selector=>selector==='[data-trim-pattern]'?{disabled:false}:null}});
      assert.equal(m.trimPatternView?.item,'Hsi_8M',node('trim-pattern-error').textContent);
      for(const [module,pattern] of [['ENTER','enter_hsi_16m'],['TRIM','set_hsi_16m_dac']]){
        const step=m.trimPatternView.uses.find(u=>u.module===module).step;
        await node('trim-pattern-uses').onclick({target:{closest(){return {dataset:{trimPatternSelect:String(step),trimPatternName:pattern}};}}});
        assert.equal(node('trim-pattern-error').textContent,'');assert.equal(m.trimPatternView.uses.find(u=>u.module===module).current,pattern);
      }
      assert.equal(m.draft.size,1);assert.equal(m.undo.length,2);await api.check();assert.equal(m.check?.result.valid,true);
      await api.save();assert.ok(m.lastSaved?.path);fs.writeFileSync(process.argv[3],JSON.stringify({path:m.lastSaved.path,changes:api.changes()}));
    }else if(process.argv[4]==='item-preview'){
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);const node=context.document.getElementById,evidence=[];
      m.selectedRow=4;api.renderLinks();await runTimer(m.itemTimer);assert.match(node('item-code').value,/double trimTar=0\.8;/);
      api.editCell({dataset:{edit:'S4'},value:'0.801'});await runTimer(m.itemTimer);assert.match(node('item-code').value,/double trimTar=0\.801;/);
      const sheet=api.sheet(),col=sheet.columns.findIndex(c=>c.label==='Recipe')+1;
      let n=col,letters='';while(n){n--;letters=String.fromCharCode(65+n%26)+letters;n=Math.floor(n/26);}
      const enter=state.links.find(x=>x.flowRow===4).patterns.find(p=>p.uses.includes('ENTER')).name;
      const before=node('item-code').value;api.editCell({dataset:{edit:letters+'4'},value:'ENTER-RUN('+enter+')-TRIM-JUDGE'});await runTimer(m.itemTimer);
      assert.ok(node('item-code').value);assert.notEqual(node('item-code').value,before);assert.match(node('item-status').textContent,/RUN/);
      evidence.push({platform:'chroma',characters:node('item-code').value.length,recipe:node('item-status').textContent});
      node('item-platform').onchange({target:{value:'s100'}});await runTimer(m.itemTimer);assert.match(node('item-code').value,/@@PLAN/);
      evidence.push({platform:'s100',characters:node('item-code').value.length});
      m.selectedRow=201;api.addRow(true);api.editCell({dataset:{edit:'B'+api.sheet().maxRow},value:'GUI_Live_Pvd'});await runTimer(m.itemTimer);
      assert.match(node('item-code').value,/Gui_Live_Pvd/);evidence.push({row:api.sheet().maxRow,characters:node('item-code').value.length});
      assert.equal(m.check,null);assert.equal(m.jobId,null);fs.writeFileSync(process.argv[3],JSON.stringify(evidence));
    }else if(process.argv[4]==='code-preview'){
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);const node=context.document.getElementById,evidence=[];
      api.editCell({dataset:{edit:'S4'},value:'0.801'});
      for(const scope of ['program','pump']){
        node('generation-scope').onchange({target:{value:scope}});
        const choices=scope==='pump'?m.state.pumpTargets:m.state.targets;
        const targets=['chroma','s100'].map(platform=>choices.find(t=>t.platform===platform));
        m.selectedTargets=new Set(targets.map(t=>t.id));await api.check();assert.ok(m.check?.result?.valid);
        assert.equal(node('preview-btn').disabled,false);await node('preview-btn').onclick();
        for(const target of targets){
          if(m.outputView.target!==target.id)await node('preview-target').onchange({target:{value:target.id}});
          assert.ok(node('output-code').value.length);assert.ok(m.outputView.files.length);
          if(scope==='program'&&target.platform==='chroma')assert.match(node('output-code').value,/double trimTar=0\.801;/);
          evidence.push({scope,target:target.id,files:m.outputView.files.length,characters:node('output-code').value.length});
        }
        assert.equal(m.jobId,null);node('output-dialog').close();
      }
      assert.equal(api.changes()[0].value,'0.801');fs.writeFileSync(process.argv[3],JSON.stringify(evidence));
    }else if(process.argv[4]==='links'){
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);m.selectedRow=4;api.renderLinks();
      const source=state.links.find(x=>x.flowRow===4);assert.ok(source);const i=source.patterns.findIndex(p=>p.uses.includes('TRIM')&&p.locations.length);assert.ok(i>=0);
      assert.ok(source.patterns[i].preview.some(w=>w.fields.some(f=>f.dynamic)));
      const location=source.patterns[i].locations[0];api.followLink(i,0);assert.equal(api.sheet().name,location.sheet);assert.equal(m.location.address,location.coordinate);
      const before=JSON.stringify(api.snapshot()),match=location.coordinate.match(/^([A-Z]+)(\d+)$/),col=[...match[1]].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0);
      const old=api.sheet().rows[Number(match[2])-1][col-1].value;let bits;
      const value=old.replace(/([01]+)\*/,(_,v)=>{bits=v.slice(0,-1)+(v.endsWith('1')?'0':'1');return bits+'*';});assert.ok(bits);
      assert.equal(JSON.stringify(api.snapshot()),before);api.editCell({dataset:{edit:location.coordinate},value});api.returnToFlow();
      await api.check();assert.ok(m.check?.result?.valid);
      const updated=m.check.result.links.find(x=>x.flowRow===4).patterns.find(p=>p.name===source.patterns[i].name);assert.ok(updated.preview.some(w=>w.fields.some(f=>f.dynamic&&f.value===bits)));
      assert.ok(context.document.getElementById('linked-body').innerHTML.includes(bits));api.followLink(i,0);assert.equal(m.location.address,location.coordinate);
      const links=m.check.result.links;
      const verify=links.find(x=>x.kind==='VERIFY'&&x.patterns.some(p=>p.preview.length&&p.locations.length&&links.some(other=>other.flowRow!==x.flowRow&&other.patterns.some(ref=>ref.name===p.name))));assert.ok(verify);
      const pi=verify.patterns.findIndex(p=>p.preview.length&&p.locations.length&&links.some(other=>other.flowRow!==verify.flowRow&&other.patterns.some(ref=>ref.name===p.name))),pattern=verify.patterns[pi];
      const users=links.filter(x=>x.patterns.some(p=>p.name===pattern.name)),other=users.find(x=>x.flowRow!==verify.flowRow);
      const edited=JSON.stringify(api.snapshot());api.returnToFlow();m.selectedRow=verify.flowRow;api.renderLinks();
      assert.ok(context.document.getElementById('linked-body').innerHTML.includes('已识别引用（'+users.length+'行）'));
      api.followLink(pi,0);assert.equal(m.location.address,pattern.locations[0].coordinate);api.returnToFlow();assert.equal(m.selectedRow,verify.flowRow);
      context.document.getElementById('linked-body').onclick({target:{closest:selector=>selector.includes('link-user')?{dataset:{linkPattern:String(pi),linkUser:String(other.flowRow)},disabled:false}:null}});
      assert.equal(m.selectedRow,other.flowRow);assert.equal(m.linkRow,other.flowRow);
      const otherPattern=other.patterns.find(p=>p.name===pattern.name);assert.deepEqual(otherPattern.preview,pattern.preview);
      assert.equal(JSON.stringify(api.snapshot()),edited);
      const verifyEvidence={flowRow:verify.flowRow,item:verify.item,pattern:pattern.name,location:pattern.locations[0],sharedRows:users.map(x=>x.flowRow),jumpRow:other.flowRow};
      const pump=links.find(x=>(x.details||[]).some(d=>d.title==='SETVPOSP')&&x.patterns.some(p=>p.name==='set_all_final_vposp'));assert.ok(pump);
      const pumpIndex=pump.patterns.findIndex(p=>p.name==='set_all_final_vposp'),aggregate=pump.patterns[pumpIndex];
      assert.equal(aggregate.locations[0].coordinate,'C14');assert.ok(aggregate.preview.some(w=>w.fields.some(f=>f.value===bits&&f.name==='BG_ABS_TRIM[3:0]')));
      m.selectedRow=pump.flowRow;api.renderLinks();api.followLink(pumpIndex,0);assert.equal(m.location.address,'C14');api.returnToFlow();assert.equal(m.selectedRow,pump.flowRow);
      assert.equal(JSON.stringify(api.snapshot()),edited);
      fs.writeFileSync(process.argv[3],JSON.stringify({item:source.item,pattern:source.patterns[i].name,location,bits,changes:api.changes(),verify:verifyEvidence,aggregate:{flowRow:pump.flowRow,item:pump.item,locations:aggregate.locations,detail:pump.details},counts:{trim:links.filter(x=>x.kind==='TRIM').length,verify:links.filter(x=>x.kind==='VERIFY').length}}));
    }else if(process.argv[4]==='draft-file'){
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);
      api.editCell({dataset:{edit:'B4'},value:'GUI_Unfinished_Draft'});
      const before=JSON.stringify(api.snapshot());
      const saved=await context.document.getElementById('draft-file-btn').onclick();
      assert.equal(saved.validation,'NOT_CHECKED');assert.ok(saved.path.includes('DRAFT_UNCHECKED_'));
      const retry=await context.document.getElementById('draft-file-btn').onclick();assert.equal(retry.path,saved.path);
      assert.equal(JSON.stringify(api.snapshot()),before);assert.equal(m.check,null);
      const response=await context.fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json','X-GUI-Session':state.testToken},body:JSON.stringify({baseSha256:state.sha256,changes:api.changes(),scope:'program',targets:state.targets.map(t=>t.id)})});
      assert.equal(response.status,422);fs.writeFileSync(process.argv[3],JSON.stringify(saved));
    }else if(['fbist','flash','flash_labels','pump'].includes(process.argv[4])){
      const scope=process.argv[4],targetField={flash:'flashTargets',fbist:'fbistTargets',flash_labels:'flashLabelTargets',pump:'pumpTargets'}[scope],fileCount={flash:31,fbist:96,flash_labels:33,pump:1}[scope];
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);
      api.editCell({dataset:{edit:scope==='pump'?'S4':'B4'},value:'GUI_Unfinished_FLOW'});
      context.document.getElementById('generation-scope').onchange({target:{value:scope}});
      m.selectedTargets=new Set(state[targetField].map(t=>t.id));
      await api.check();assert.ok(m.check?.result?.valid);assert.equal(m.check.result.scope,scope);
      assert.equal(context.document.getElementById('save-btn').disabled,true);
      const request={...api.draftPayload(),scope,targets:[...m.selectedTargets],checkId:m.check.result.checkId};
      const post=(url,payload)=>context.fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-GUI-Session':state.testToken},body:JSON.stringify(payload)});
      await api.generate();assert.ok(m.jobId);
      const retry=await post('/api/generate',request),retryBody=await retry.json();assert.equal(retryBody.jobId,m.jobId,JSON.stringify(retryBody));
      let job;const deadline=Date.now()+120000;
      do{await new Promise(resolve=>setTimeout(resolve,100));const response=await context.fetch('/api/job?id='+m.jobId,{headers:{'X-GUI-Session':state.testToken}});job=await response.json();}while(job.status==='running'&&Date.now()<deadline);
      assert.equal(job.status,'completed',JSON.stringify(job));m.busy=false;
      const evidence=[];
      for(let target=0;target<job.result.outputs.length;target++){
        await api.openOutput(target);const files=m.outputView.files.filter(f=>/\.(pat|sd)$/.test(f.path));
        assert.equal(files.length,fileCount);assert.ok(files.every(f=>f.path.includes('set_all_final_vposp')===(scope==='pump')));
        await api.previewFile(files[0].path);assert.ok(context.document.getElementById('output-code').value.length);
        evidence.push({platform:job.result.outputs[target].platform,files:files.length,preview:files[0].path});
      }
      assert.equal((await post('/api/save',request)).status,422);
      assert.equal((await post('/api/generate',{...request,scope:'patterns'})).status,422);
      api.editCell({dataset:{edit:'B4'},value:'GUI_Changed_After_Check'});
      assert.equal((await post('/api/generate',{...request,changes:api.changes()})).status,422);
      fs.writeFileSync(process.argv[3],JSON.stringify(evidence));
    }else if(process.argv[4]==='resources'){
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);
      const originalItem=api.sheet().rows[3][1].value;
      const evidence=[],headers={'X-GUI-Session':state.testToken,'Content-Type':'application/json'};
      for(const [scope,platform,variant] of [['pin','s100','production'],['patterns','chroma','lab']]){
        context.document.getElementById('generation-scope').onchange({target:{value:scope}});
        const choices=scope==='pin'?m.state.pinTargets:m.state.targets,target=choices.find(t=>t.platform===platform&&t.cp==='CP3'&&t.variant===variant);assert.ok(target);
        m.selectedTargets.add(target.id);
        api.editCell({dataset:{edit:'B4'},value:scope==='pin'?'GUI_Unfinished_FLOW':String(originalItem)});
        await api.check();assert.ok(m.check?.result?.valid);assert.equal(m.check.result.scope,scope==='pin'?'pin':'program');
        await api.generate();assert.ok(m.jobId);
        const job=m.jobId,deadline=Date.now()+60000;
        while(m.busy&&Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,200));await api.pollJob(m.jobRevision);}
        assert.equal(m.busy,false);
        const result=await (await fetch(state.testOrigin+'/api/job?id='+job,{headers})).json();assert.equal(result.status,'completed',JSON.stringify(result));
        const payload={...api.draftPayload(),checkId:m.check.result.checkId,targets:[target.id],scope,validate:false};
        const repeat=await (await fetch(state.testOrigin+'/api/generate',{method:'POST',headers,body:JSON.stringify(payload)})).json();assert.equal(repeat.jobId,job,JSON.stringify(repeat));
        const invalid=await fetch(state.testOrigin+'/api/generate',{method:'POST',headers,body:JSON.stringify({...payload,scope:'unsupported'})});assert.equal(invalid.status,422);
        if(scope==='pin'){
          const misuse=await fetch(state.testOrigin+'/api/save',{method:'POST',headers,body:JSON.stringify(payload)});assert.equal(misuse.status,422);
        }
        const stale=await fetch(state.testOrigin+'/api/generate',{method:'POST',headers,body:JSON.stringify({...payload,checkId:'old-check'})});assert.equal(stale.status,422);
        await api.openOutput(0);const files=m.outputView.files.filter(f=>!f.path.endsWith('.json'));assert.ok(files.length);
        if(scope==='pin'){assert.equal(files.length,1);assert.match(files[0].path,/pin_resources\.prj$/);}else assert.ok(files.every(f=>/\.(pat|sd|sr)$/i.test(f.path)));
        await api.previewFile(files[0].path);const content=context.document.getElementById('output-code').value;assert.ok(content.length);
        if(scope==='pin')assert.match(content,/@@PIN_DEFINE_TABLE/);
        evidence.push({scope,job,files:files.length,preview:files[0].path,path:result.result.outputs[0].path});
      }
      assert.equal(api.changes().length,0);fs.writeFileSync(process.argv[3],JSON.stringify(evidence));
    }else if(process.argv[4]==='batch'){
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);m.selectedRow=208;m.selectedColumn=2;
      api.openBatchFill();const node=context.document.getElementById;node('batch-end').value='210';node('batch-value').value='GUI_Batch_Verify';
      api.previewBatchFill();api.applyBatchFill();await api.check();assert.ok(m.check?.result?.valid);
      assert.equal(api.changes().length,3);
      fs.writeFileSync(process.argv[3],JSON.stringify({...api.draftPayload(),checkId:m.check.result.checkId}));
    }else if(process.argv[4]==='output'){
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);m.jobId=state.jobId;
      const before=JSON.stringify(api.snapshot()),verified=[];
      for(const target of [0,1]){
        await api.openOutput(target);
        const main=m.outputView.files.find(f=>/\.(pln|prg)$/i.test(f.path));assert.ok(main);
        await api.previewFile(main.path);
        assert.match(context.document.getElementById('output-code').value,/Gui_Power_Group_Copy/);
        const resource=m.outputView.files.find(f=>/\.(pat|sd)$/i.test(f.path));assert.ok(resource);await api.previewFile(resource.path);
        assert.ok(context.document.getElementById('output-code').value.length);
        verified.push({target,main:main.path,resource:resource.path,files:m.outputView.files.length});
      }
      assert.equal(JSON.stringify(api.snapshot()),before);fs.writeFileSync(process.argv[3],JSON.stringify(verified));
    }else if(process.argv[4]==='group'){
      context.fetch=(url,options)=>fetch(state.testOrigin+url,options);m.selectedRow=192;
      await api.openGroupCopy();await api.confirmGroupCopy('GUI_Power_Group_Copy');
      fs.writeFileSync(process.argv[3],JSON.stringify({...api.draftPayload(),checkId:m.check.result.checkId,_checkedResult:m.check.result}));
    }else{
      m.selectedRow=201;api.addRow(true);api.editCell({dataset:{edit:'B'+api.sheet().maxRow},value:'GUI_Row_Verify'});
      fs.writeFileSync(process.argv[3],JSON.stringify(api.draftPayload()));
    }
  }
  console.log(`${results.filter(x=>x[1]).length}/${results.length} passed; offline DOM stubs, no browser visual verification`);
  if(results.some(x=>!x[1]))process.exitCode=1;
})();
