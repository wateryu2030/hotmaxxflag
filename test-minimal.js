module.exports = {
  name: 'test-minimal',
  version: '1.0.0',
  tools: [
    {
      name: 'test_minimal',
      description: '最小测试工具',
      inputSchema: { type: 'object', properties: {} },
      handler: async () => ({ 
        success: true, 
        message: '最小插件工作正常',
        time: new Date().toISOString()
      })
    }
  ]
};
