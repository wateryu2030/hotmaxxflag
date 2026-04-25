module.exports = {
  id: 'test-plugin',
  name: 'Test Plugin',
  version: '1.0.0',
  description: '测试插件',
  register(api) {
    api.registerTool({
      name: 'test_ping',
      description: '测试工具',
      parameters: { type: 'object', properties: {} },
      async execute() {
        return { success: true, message: '插件工作正常' };
      }
    });
  }
};
