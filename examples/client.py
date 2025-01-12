from asyncio import Future, run as async_run
from websockets.asyncio.client import connect, ClientConnection
from websockets.exceptions import ConnectionClosedError
from json import loads as json_parse, dumps as json_stringify

CLEAR_CONSOLE: str = '\033[H\033[J'
                                
class SocketClient:
    '''Implements a websocket client'''
    
    def __init__(self, host: str = 'localhost', port: int = 8080, protocol_version: int = 1) -> None:
        '''Constructor function'''
        
        self.host: str = host
        self.port: int = port
        self.uri = f'ws://{host}:{port}'
        
        self.protocol_version: int = protocol_version
        
        self.queue_size: int = 100
        self.send_queue: list[dict] = []
        '''Request that are waiting for the requests from the awaited queue to be resolved.'''
        self.awaited_queue: dict[str, dict] = {}
        '''Requests that have already been sent to Minecraft's websocket but haven't been responded to yet.'''
        
        self.subscribed_events: set[str] = set()
        self.websocket: ClientConnection | None = None
    
    async def start(self):
        '''Starts the client'''
        try:
            async with connect(self.uri) as websocket:
                print(f'{CLEAR_CONSOLE}Connected! Press Ctrl+C to stop...')
                self.websocket = websocket
                await self.proxy()
                await Future()
        except ConnectionRefusedError:
            print("The remote computer refused the network connection")
    
    async def send(self, data: str) -> None:
        '''Sends a message to the server'''
        await self.websocket.send(data)

    async def receive(self, data: str) -> None:
        '''Executes each time the client receives a message from the server'''
        
        # Identidy as not minecraft if got a `geteduclientinfo` request.
        try:
            json: dict = json_parse(data)
            command: str = json.get('body', {}).get('commandLine')
            if command == 'geteduclientinfo':
                await self.send("Not Minecraft client")
        except: pass

        pass

    async def proxy(self) -> None:
        self.connected()
        try:
            async for msg in self.websocket:
                await self.receive(msg)
        except ConnectionClosedError:
            self.disconnected()
    
    
    def connected(self) -> None:
        print('Connected to server!')
    def disconnected(self) -> None:
        print('Disconnected from server...')

if __name__ == "__main__":
    async_run(SocketClient().start())