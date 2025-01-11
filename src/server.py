from asyncio import Future, run as async_run
from websockets import serve
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosedError
from json import loads as json_parse, dumps as json_stringify
from uuid import uuid4
from pyperclip import copy as clipboard_copy
from typing import Literal

CLEAR_CONSOLE: str = '\033[H\033[J'
                                
class SocketServer:
    '''Implements a websocket server that interact with Minecraft's websocket API'''
    
    MessagePurposes = Literal['commandRequest', 'subscribe', 'unsubscribe']
    MessageTypes = Literal['commandRequest']
    SocketSubscriptionStatus = Literal['subscribe', 'unsubscribe']
    SocketEvents = Literal[
        'BlockBroken', 'BlockPlaced', 'CameraUsed', 'EndOfDay',
        'EntitySpawned', 'ItemAcquired', 'ItemCrafted (disabled)',
        'ItemDropped', 'ItemEquipped', 'ItemInteracted', 'ItemSmelted',
        'ItemUsed', 'MobKilled', 'PlayerBounced', 'PlayerDied',
        'PlayerMessage', 'PlayerTeleported', 'PlayerTravelled'
    ]
    
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
        self.minecraft_websocket: ServerConnection | None = None
        
        self.client_websockets: list[ServerConnection] = []
        '''This list doesn't include the minecraft websocket connection'''
    
    async def start(self):
        '''Starts the server'''
        async with serve(self.proxy, self.host, self.port):
            print(f'{CLEAR_CONSOLE}Ready. Execute \'/wsserver {self.uri}\' on Minecraft to connect. Press Ctrl+C to stop')
            clipboard_copy(f'/wsserver {self.uri}')
            await Future()
    
    async def send(self, websocket: ServerConnection, data: str) -> None:
        '''Sends a message to a websocket'''
        await websocket.send(data)
    
    async def identify_minecraft(self, websocket: ServerConnection) -> None:
        '''
        Executed when a client joins, then sends a special request to identify
        whether the client connected is Minecraft's websocket, if it is then
        the `minecraft_websocket` variable is set respectively.
        '''
        
        requestId: str = str(uuid4())
        msg: dict = {
            'header': {
                'version': self.protocol_version,
                'requestId': requestId,
                'messagePurpose': 'commandRequest',
                'messageType': 'commandRequest'
            },
            'body': {
                'version': self.protocol_version,
                'commandLine': 'geteduclientinfo',
                'origin': {'type': 'player'}
            }
        }
        await self.send(websocket, json_stringify(msg))
        
        try:
            response: dict = json_parse(await websocket.recv())
        except ConnectionClosedError:
            print('Connection closed when identifying')
            return
        
        responseRequestId: dict = response.get('header', {}).get('requestId')
        if requestId != responseRequestId: return
        
        self.minecraft_websocket = websocket
        
        # Notify that the Minecraft connection established
        await self.queue_minecraft_command('say Pairing succesful!')
    
    async def queue_minecraft_socket(self,
            messagePurpose: MessagePurposes,
            messageType: MessageTypes = 'commandRequest',
            body: dict = {}
        ):
        '''Adds a message to the request queue.'''
        body['version'] = self.protocol_version
        
        requestId: str = str(uuid4())
        msg: dict = {
            'header': {
                'version': self.protocol_version,
                'requestId': requestId,
                'messagePurpose': messagePurpose,
                'messageType': messageType,
            },
            'body': body
        }

        self.send_queue.append(msg)
        
        await self.minecraft_send_request_from_queue()
    
    async def queue_minecraft_command(self, cmd: str):
        '''Adds a command execution request to the request queue.'''
        
        await self.queue_minecraft_socket('commandRequest', body = {
            'commandLine': cmd,
            'origin': {'type': 'player'}
        })
    
    async def queue_minecraft_socket_subscription(self,
            event_name: SocketEvents,
            subscriptionStatus: SocketSubscriptionStatus = 'subscribe'
        ):
        '''
        Adds a subscription / unsubscription request to the request queue.\n
        Executes the `event` method when the event is fired.
        '''
        
        self.subscribed_events.add(event_name)
        await self.queue_minecraft_socket(subscriptionStatus, body = {'eventName': event_name})
    
    async def queue_scriptevent(self, identifier: str, data: str) -> None:
        '''
        Adds a 'scriptevent' command execution request to the request queue.\n
        Send a script event to Minecraft (Wrapper for `queue_minecraft_command`)
        '''
        
        await self.queue_minecraft_command(f'scriptevent {identifier} {data}')
    
    async def event(self, eventName: str, data: str) -> None:
        '''Executes for subscribed events, subscribe events with `queue_minecraft_socket_subscription`'''
        pass

    async def receive(self, websocket: ServerConnection, data: str) -> None:
        '''Executes each time the websocket server receives a message from a client (use `receive_minecraft` for Minecraft's websocket)'''
        if websocket == self.minecraft_websocket:
            await self.receive_minecraft(data)
            return
        pass
    
    async def receive_minecraft(self, data: str) -> None:
        '''Executes each time the websocket server receives a message from Minecraft's websocket (use `receive` for client's websocket)'''
        data: dict = json_parse(data)
        body: dict = data['body']
        header: dict = data['header']

        # Execute events for subscribed events
        for eventName in self.subscribed_events:
            if body.get('eventName', None) == eventName:
                self.event(eventName, data)
        
        # If we get a command response, update the queue
        if header['messagePurpose'] == 'commandResponse':
            if header['requestId'] in self.awaited_queue:
                # Get the awaited request that was responded
                awaited: dict = self.awaited_queue[header['requestId']]
                
                # Print errors
                if body['statusCode'] < 0:
                    command: str = awaited['body']['commandLine'],
                    print(command, body['statusMessage'])
                
                # Remove the request from the awaited queue
                del self.awaited_queue[header['requestId']]
        
        await self.minecraft_send_request_from_queue()     
    
    async def minecraft_send_request_from_queue(self) -> None:
        '''Sends requests from the queue if possible.'''
        
        # The count of new requests that can be awaited
        count = self.queue_size - len(self.awaited_queue)
        # Loop for each command in n-count elements from the send queue
        for command in self.send_queue[:count]:
            # Send the command in send_queue, and add it to the awaited_queue
            await self.send(self.minecraft_websocket, json_stringify(command))
            self.awaited_queue[command['header']['requestId']] = command
        
        # Remove n-count elements from the send_queue
        self.send_queue = self.send_queue[count:]

    async def proxy(self, websocket: ServerConnection) -> None:
        if self.minecraft_websocket == None:
            await self.identify_minecraft(websocket)
            
        if websocket == self.minecraft_websocket:
            self.minecraft_connected()
        else:
            self.client_connected(websocket)

        try:
            async for msg in websocket:
                await self.receive(websocket, msg)
        except ConnectionClosedError:
            if websocket == self.minecraft_websocket:
                self.minecraft_disconnected()
            else:
                self.client_disconnected(websocket)
    
    
    def client_connected(self, websocket: ServerConnection):
        print('Client connected!')
    def client_disconnected(self, websocket: ServerConnection):
        print('Client disconected...')
    
    def minecraft_connected(self):
        print('Minecraft connected!')
    def minecraft_disconnected(self):
        print('Minecraft disconected...')

if __name__ == "__main__":
    async_run(SocketServer().start())