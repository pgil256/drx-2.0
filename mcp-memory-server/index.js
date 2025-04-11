// MCP Memory Server - Extends filesystem capabilities with memory storage
const { MCPServer } = require('@modelcontextprotocol/server');
const { FilesystemServer } = require('@modelcontextprotocol/server-filesystem');
const fs = require('fs');
const path = require('path');

// Path to the KneeSpa project
const BASE_PROJECT_PATH = process.argv[2] || '.';
// Path for storing memories
const MEMORY_FILE_PATH = path.join(BASE_PROJECT_PATH, '.mcp-memories.json');

class MemoryFilesystemServer extends MCPServer {
  constructor() {
    super('memory-filesystem');
    
    // Initialize memory storage
    this.memories = {};
    this.loadMemories();
    
    // Create underlying filesystem server
    this.filesystemServer = new FilesystemServer();
    this.filesystemServer.initialize(BASE_PROJECT_PATH);
    
    // Register filesystem functions
    this.registerFilesystemFunctions();
    
    // Register memory functions
    this.registerFunction('store_memory', this.storeMemory.bind(this), {
      description: 'Store information for later retrieval',
      parameters: {
        type: 'object',
        properties: {
          key: { type: 'string', description: 'The key to store the memory under' },
          value: { type: 'string', description: 'The value to store' }
        },
        required: ['key', 'value']
      }
    });
    
    this.registerFunction('retrieve_memory', this.retrieveMemory.bind(this), {
      description: 'Retrieve previously stored information',
      parameters: {
        type: 'object',
        properties: {
          key: { type: 'string', description: 'The key to retrieve the memory for' }
        },
        required: ['key']
      }
    });
    
    this.registerFunction('list_memories', this.listMemories.bind(this), {
      description: 'List all available memories',
      parameters: {
        type: 'object',
        properties: {}
      }
    });
    
    this.registerFunction('delete_memory', this.deleteMemory.bind(this), {
      description: 'Delete a stored memory',
      parameters: {
        type: 'object',
        properties: {
          key: { type: 'string', description: 'The key of the memory to delete' }
        },
        required: ['key']
      }
    });

    console.log(`Memory filesystem server initialized with base path: ${BASE_PROJECT_PATH}`);
    console.log(`Using memory storage at: ${MEMORY_FILE_PATH}`);
  }
  
  // Register all the filesystem functions
  registerFilesystemFunctions() {
    // Get all methods from the filesystem server
    const filesystemFunctions = this.filesystemServer.getFunctions();
    
    // Register each function
    for (const [name, func] of Object.entries(filesystemFunctions)) {
      this.registerFunction(name, async (params) => {
        return await this.filesystemServer.executeFunction(name, params);
      }, func.schema);
    }
  }
  
  // Memory management functions
  loadMemories() {
    try {
      if (fs.existsSync(MEMORY_FILE_PATH)) {
        const data = fs.readFileSync(MEMORY_FILE_PATH, 'utf8');
        this.memories = JSON.parse(data);
        console.log(`Loaded ${Object.keys(this.memories).length} memories from storage`);
      } else {
        console.log('No existing memories found, starting with empty memory');
      }
    } catch (error) {
      console.error('Error loading memories:', error);
      this.memories = {};
    }
  }
  
  saveMemories() {
    try {
      fs.writeFileSync(MEMORY_FILE_PATH, JSON.stringify(this.memories, null, 2), 'utf8');
      console.log('Memories saved to disk');
    } catch (error) {
      console.error('Error saving memories:', error);
    }
  }
  
  async storeMemory(params) {
    const { key, value } = params;
    this.memories[key] = {
      value,
      timestamp: new Date().toISOString()
    };
    this.saveMemories();
    return { success: true, message: `Memory stored with key: ${key}` };
  }
  
  async retrieveMemory(params) {
    const { key } = params;
    if (this.memories[key]) {
      return { 
        success: true, 
        memory: this.memories[key].value,
        timestamp: this.memories[key].timestamp
      };
    }
    return { success: false, message: `No memory found with key: ${key}` };
  }
  
  async listMemories() {
    const memoryList = Object.entries(this.memories).map(([key, data]) => ({
      key,
      timestamp: data.timestamp
    }));
    return { success: true, memories: memoryList };
  }
  
  async deleteMemory(params) {
    const { key } = params;
    if (this.memories[key]) {
      delete this.memories[key];
      this.saveMemories();
      return { success: true, message: `Memory with key '${key}' deleted` };
    }
    return { success: false, message: `No memory found with key: ${key}` };
  }
}

// Create and start the server
const server = new MemoryFilesystemServer();
server.start();
