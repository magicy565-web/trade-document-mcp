# Trade Document MCP | V0.1–V0.5 engineering roadmap

基线：main 9d53f51 (0.1.0). V0.1 源码已具备 12 个工具、SQLite 版本、Decimal、Ed25519 审批、基础 Excel/PDF；CI 尚未通过。此文件是整改和开发验收合同，不代表实现已经完成。每个阶段单独 PR、可运行演示、独立 QA、签核后才打版本标签。不要扩展到采购寻源、需求洞察、支付或自主交易。

## 共同原则与目标架构

- Host/LLM 负责理解、提取、翻译、候选映射；MCP 服务端负责结构化计算、数据来源、规则、文档、权限与审计。未知不得编造；候选、买方请求、卖方报价、双方确认、争议状态独立。
- TradeCase -> Party/Address/Product/Variant -> OrderRevision -> ShipmentRevision -> DocumentIntent -> RulePackVersion -> TemplateVersion -> PreviewBundle -> Approval -> IssuedBundle -> AuditResult. 每个对象有租户、ID、修订、来源、时间、状态。
- Decimal 支持小数数量及单位换算，币种精度、折扣、运费/保险、付款里程碑及分摊政策明确；禁止隐式汇率、税率及货值。
- 人类确认价格、费用、折扣、交期、贸易术语、收款账户、样品政策、海关估值及归类、合同/出单/外发。审批绑定订单摘要、模板/规则版本及预览文件哈希；更改自动失效。Agent 不持有签署密钥。
- 商业 PI、Sample PI、Sample Order Sheet、Commercial Invoice、Packing List、Customs Supporting Invoice 是不同用途；商业应付金额和申报价值分离；不得把免费样品等同零申报价值。
- Rules: global -> origin/destination -> purpose -> product/transport -> buyer/tenant. 法规、官方指导、承运商建议、企业政策分层；仅经专业复核、有效日期/适用范围明确的规则才能阻断正式出单。未知区域走通用商业草稿并提示人工，不宣称合规。
- 原始资料与许可证见 knowledge/corpus/registry.json；知识检索优先于微调。私有原件、真实订单、银行资料、签署密钥、客户资料绝不进公共 Git；未经授权资料不得进入训练。合成样本必须标注。

## V0.1 修复：商业 PI 和样品订单垂直闭环

P0: 修复 CI、锁依赖、Python 3.11/3.12；保留现有 12 工具兼容性。重构 Party/Address、Product/Variant、PaymentSchedule、DeliveryTerms、SampleSpec、Fee、Evidence、BeneficiaryRef；支持整数与十进制数量、拆分付款、规格/图片、打样费/模具费/运费、收货地址、报价有效期、条件抵扣；缺失和冲突可逐字段解答。账户通过企业档案预确认，修改走独立高权限流程。
P0: 四种原创建议模板（Standard PI、Image PI、Sample PI、Sample Order Sheet），A4/Letter、英文、长表/页眉页脚/签署区；无图/多图、长文本、非 ASCII 名称和零价案例。草稿可明确 Pending，正式版不可缺关键字段；输出可编辑 XLSX 及一致的 PDF。
P0: 审批包含预览哈希、规则/模板版本、签名及有效期；检查版本竞争、重复签署、越权、归档；独立审单覆盖全部金额公式、字段、图片、重复 SKU/编号、PDF 可读性及视觉分页。
P0: 扩展 5 个 Skills 的 SOP、规则、反例及回归用例；Host 可做结构化提取并提供原文位置和确认状态。
验收：CI 两环境绿、真实 MCP stdio 集成、四类输出实物及人工视觉审核、至少 100 个独立标注业务场景（合成/真实分列，不把参数变体冒充独立订单）；所有关键字段、确定性金额和越权阻断在测试中 100%；已知限制清单。真实订单一次通过率未达 95% 不得标为已实现。

## V0.2 国际知识库与 PI 标准

依赖 V0.1 gate。建立 source_registry、原件只读仓、权利许可记录、页码/坐标标注、字段映射、规则注册器、版本及失效机制、证据检索；原始资料解析失败进入隔离，不能直接注入系统提示。使用 knowledge/pi-standard.json 为初始工程规范；不是法律意见。
优先 EU（DE/FR）、US、GB、CA、JP、AU；随后 AE、IN、TR、MA，只有二级来源的区域保持 review_only，直到当地官方证据和专业审核通过。商业 PI 不强制所有海关字段；进口用途才启用对应规则。美国 19 CFR 141.85 特定进口人声明单独意图，默认禁用直出。免费/收费样品分离货值及应付金额。
支持 ISO 国家/币种、带单位的 Decimal 数量、税号类型、商品原产地、HS 候选/地区税则编码（非自主定类）、公制/英制展示、英文/德文/法文及可扩展本地化（人工确认翻译不改变条款）。
新增建议工具：list_jurisdiction_profiles、resolve_document_requirements、get_rule_evidence、validate_jurisdiction、search_knowledge、get_source_reference。每条 finding 含 rule_id、source_id、scope、severity、evidence、resolution。
验收：至少 300 个独立场景，覆盖 EU 90、US 90、GB/CA 40、JP/AU 40、其他 40；按来源和企业分组，真实持出测试与合成回归分列；不得把 95% 作为合成通过率。免费样品、日期、币种、海关场景及冲突规则有负例；至少每个正式支持区域有已审核来源和文件实例。

## V0.3 企业 Excel 专员与模板学习

实现模板接入、扫描结构/合并/命名区域/公式/图片/样式/多 sheet/打印布局、候选字段映射及人工确认、版本化模板指纹、动态明细行和公式范围更新；对宏、外部链接、恶意公式、超大 ZIP、未知结构进行隔离/拒绝。仅支持经测试模板族，不宣称任意 Excel 完美复刻。
统一渲染布局或可靠转换路径；Excel 公式缓存经独立计算验证；PDF 对比字体、溢出、图片、页码、标题重复、金额、语言和模板一致性。保护未映射固定内容；输出工作副本与锁定正式文件分离。
新增工具建议：inspect_template、propose_template_mapping、confirm_template_mapping（人类）、validate_template、compare_template_output、render_document_bundle、visual_audit。支持模板变更失效及回退。
验收：至少 30 个获授权的不同企业模板族（多行业、2+ 页/多 SKU、合并/Logo/图片/公式、A4/Letter），人工确认映射后复用，原版/输出视觉证据，不能自动识别时明确拒绝并给映射建议。严禁训练集和验收集同模板泄漏。

## V0.4 全流程单证与报关辅助

统一 TradeCase 支持 PO->PI->实际批次出货->CI/PL；按实际 shipment revision 计算，不照搬原 PI。支持分批、余量、变更、包装层级、净/毛重、体积、箱唛、货物原产地、不同收货人。合同/Shipping Instruction/原产地证申请资料均为草稿；信用证基础差异提示不替代专业审单。
CustomsSupportingInvoice 单独用途；免费货物估值证据、币种、费用、适用海关规则及申报要素；CN 出口报关预录入草稿和目的地资料包仅在审核通过的适用范围内，禁止自动申报、猜 HS、保证关税/通关。国内税务发票另项目/接口。
新增建议工具：create_shipment、generate_commercial_invoice、generate_packing_list、draft_sales_contract、prepare_customs_support、validate_shipment、cross_check_documents、export_document_bundle。所有正式签核均复用审批和版本锁。
验收：至少 150 个独立跨文件业务场景；分批、漏装、退货/修订、运费、金额/重量/单位矛盾、错原产地均拦截；每类输出样本和人工审单；实际出口/进口合规仍由专业人负责。

## V0.5 企业级 MCP 与生产验收

提供 stdio + 经认证的远程 MCP（Streamable HTTP），租户隔离、RBAC、审签页面/回调、最小权限、短效文件下载链接、对象存储、数据库迁移/备份恢复、审计日志、幂等键、异常恢复、任务重试、版本化 API/契约测试、限流、监控和可追溯运维。企业资料/客户/商品/模板知识按租户隔离；收款变更需独立验证与审批。禁止模型能读签署密钥；外部发送另授权，不在默认功能中。
连接 buyer/supplier/ERP 以明确的订单和文件契约，不依赖其内部模型；提供模拟集成、部署指南、配置示例、权限/故障演练、SBOM/依赖扫描、数据保留与删除策略。
评测：累计至少 500 个独立场景；正式 95% 指标仅以获得授权且专业人员双审的盲测真实业务报告为依据，并公布实际样本量、分布、置信区间、失败类型、未覆盖范围。建议至少 200 个真实盲测样本再宣布目标达成；分母为预先定义的适用且资料齐全订单，缺失/冲突订单另测正确澄清/阻断率，并同时报告全量自动完成率、人工补充率、错误放行率、格式返工率。金额/关键字段和权限拦截测试 100%，不能据此保证生产永远无错。
验收：CI、实机客户端、多租户越权/重放/篡改测试、备份恢复、故障注入、独立业务/视觉 QA；至少 3 家授权企业试点（建议值）、人工审签，真实一次通过率 >=95% 才能宣称达标。发布带版本化规则、样板来源清单、签核报告及回滚流程。

## 交付顺序与 DoD

0.1 整改 -> 0.2 国家规则 -> 0.3 企业模板 -> 0.4 CI/PL/报关辅助 -> 0.5 企业部署。每阶段先写验收用例和契约，再实现；保留旧调用兼容或提供迁移。每次提交关联验收项、真实调用记录、测试日志、脱敏文件、视觉审查结果、限制。不以工具数量、文档数量或合成测试通过率冒充真实可用性。此路线图采用分阶段技术选择及样本数量建议，需产品负责人审批后执行。
