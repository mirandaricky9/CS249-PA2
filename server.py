import argparse
import http.server
import json
import re
import socket
import threading
import time
import traceback
import urllib.parse
import sys
from typing import NoReturn

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

# Creating a class to store "database"-related information (imported from PA1)
# Added an identifier for messages based on which channel it is in
# i.e. unique message id based on the channel 
class Store:
    def __init__(self, channels):
        self.users = {}  # dictionary, map username to time() for "date joined"
        self.channels = {}  # dict that maps channel name to a list of users, initiated on startup
        self.messages = []  # a list of Message() objects will go here
        self.replicas = {} # stores a tuple (channel, message_id) to a dictionary with keys {"message_id", "username", "text"}
        self.channel_message_id_tracker = {} # dict that maps channel id to that channel's next id
        self.lock = threading.RLock()
        self.regex_username = re.compile("^[A-Za-z0-9_-]+$")
        self.regex_channel = re.compile("^#[A-Za-z0-9_-]+$")

        # Create the channels
        for channel in channels:
            self.create_channel(channel)

    def register_user(self, name):
        with self.lock:
            if self.regex_username.search(name):
                if name in self.users:
                    raise CONFLICT(
                        f"Username {name} already exists. Please choose a different one"
                    )
                else:
                    self.users.update({name: time.time()})
            else:
                raise INVALID_USERNAME(
                    "Username is invalid. Only letters, numbers, underscores, and hyphens are allowed. Please try again."
                )
    def post_message(self, channel, user, text):
        with self.lock:
            if self.regex_channel.search(channel):
                if channel in self.channels:
                    if user in self.users:
                        if user in self.channels[channel]:
                            message_id = self.channel_message_id_tracker[channel]

                            message = Message(
                                message_id, channel, user, text, time.time()
                            )
                            self.messages.append(message)

                            self.channel_message_id_tracker[channel] += 1
                            return message

                        else:
                            raise NOT_FOUND("User is not part of the channel")

                    else:
                        raise NOT_FOUND("User does not exist.")

                else:
                    raise NOT_FOUND("Channel name not found.")
            else:
                raise INVALID_CHANNEL("Channel name is invalid")

    # Joins a user on a channel
    def join(self, user, channel):
        channels = self.channels
        users = self.users

        with self.lock:
            # check if channel format is allowed
            if self.regex_channel.search(channel):
                # check if user exists
                if user in users:
                    # check if channel exists
                    if channel in channels:
                        # at this point, user and channel exist.
                        # Add user to the list of members of the channel

                        members_list = channels[channel]
                        if user not in members_list:
                            members_list.append(user)

                    else:
                        raise NOT_FOUND("Channel does not exist.")
                else:
                    raise NOT_FOUND("User does not exist.")
            else:
                raise INVALID_CHANNEL("Channel name format is not allowed.")


    def create_channel(self, channel):
        with self.lock:
            channels = self.channels
            channel_message_id_tracker = self.channel_message_id_tracker

            # Create a new channel and add it to the list of channels
            # initialize it with an empty list
            # Check format of name of channel
            if self.regex_channel.search(channel):
                channels.update({channel: []})
                channel_message_id_tracker.update({channel: 1})
            else:
                raise INVALID_CHANNEL("Channel name format is not allowed.")

    def leave(self, user, channel):
        users = self.users
        channels = self.channels

        with self.lock:
            if self.regex_channel.search(channel):
                # check if user and channel exist
                if user in users:
                    if channel in channels:
                        members_list = channels[channel]
                        if user in members_list:
                            members_list.remove(user)
                    else:
                        raise NOT_FOUND("Channel does not exist!")
                else:
                    raise NOT_FOUND("User does not exist!")
            else:
                raise INVALID_CHANNEL("Invalid channel name format.")

    # Get methods below

    # Gets the list of channels
    def get_channels(self):
        with self.lock:
            return list(self.channels.keys())

    # gets the list of all users
    def get_users(self):
        with self.lock:
            return list(self.users)

    # Gets the list of users in a channel
    def get_users_of_channel(self, channel):
        channels = self.channels
        with self.lock:
            if self.regex_channel.search(channel):
                if channel in channels:
                    return list(channels[channel])
                else:
                    # returns NOT_FOUND error
                    raise NOT_FOUND("Channel not found.")
            else:
                raise INVALID_CHANNEL("Channel format is not allowed.")

    # gets the message history of a channel, default to only the last 30 messages unless specified
    def get_channel_history(self, channel, limit=30):
        messages = self.messages
        channels = self.channels
        history = []
        counter = 0  # counter that is used to check the limit. if counter reaches limit, break from for loop
        # check format of channel; raise exception if invalid
        with self.lock:
            if self.regex_channel.search(channel):
                if limit <= 0:
                    raise BAD_REQUEST(
                        "Please choose a number greater than 0 for history."
                    )
                if channel in channels:
                    for message in reversed(messages):
                        # if the message's channel matches the channel we are looking for
                        if message.get_channel() == channel:
                            # grab details

                            history.append(message.to_dict())
                            counter += 1
                            if counter == limit:
                                break
                else:
                    raise NOT_FOUND("Channel does not exist.")
            else:
                raise INVALID_CHANNEL("Channel format is not allowed.")

            # make the list of history in order from oldest to newest.
            history.reverse()
            return history

    # Boolean variable to check if the user exists already
    def is_user(self, user):
        with self.lock:
            return user in self.users

    # helper method - returns a boolean
    def is_user_in_channel(self, user, channel):
        channels = self.channels
        with self.lock:
            if channel in channels:
                return user in self.channels[channel]
            else:
                raise NOT_FOUND("Channel does not exist.")

    # Removes the user from all channels
    # essentially, call leave on all channels that the user is in.
    def remove_user_from_channels(self, user):
        channels = self.channels
        with self.lock:
            for channel in channels:
                if self.is_user_in_channel(user, channel):
                    self.leave(user, channel)

    # stores the replica of a channel and message
    def store_replica(self, channel, message_id, username, text):
        with self.lock:
            key = (channel, message_id)
            if key in self.replicas:
                return False
            self.replicas[key] = {"message_id" : message_id,
                                  "username": username,
                                  "text": text}
            return True

    def get_replica(self, channel):
        with self.lock:
            if not self.regex_channel.search(channel):
                raise INVALID_CHANNEL("Channel format is not allowed.")
            if channel not in self.channels:
                raise NOT_FOUND("Channel does not exist.")

            message_ids = []
            history = []
            # for each tuple in replicas
            for key in self.replicas:
                # store two variables
                replica_channel, message_id = key
                # check if replica_channel is equal to channel
                if replica_channel == channel:
                    message_ids.append(message_id)

            message_ids.sort()

            for message_id in message_ids:
                replica = self.replicas[(channel, message_id)]
                history.append(dict(replica))

            return history

# A class to keep track of other peers 
class Peer:
    def __init__(self, server_id, store, cluster_config):
        self.id = server_id
        self.cluster_config = cluster_config
        # Grab priority from cluster_config
        self.priority = cluster_config["servers"][server_id]["priority"]
        self.store = store
        # Grab the peer ids from cluster config
        self.peer_ids = [sid for sid in cluster_config["servers"] if sid != server_id]
        # assume all peers are alive at start
        self.alive = {sid: True for sid in self.peer_ids}
        # assume all peers have no misses
        self.misses = {sid: 0 for sid in self.peer_ids}
        
        self.current_leader = None
        self.state_lock = threading.RLock()


    def peer_call(self, target_id, obj, timeout=2) -> dict:

        sock = socket.create_connection(target_id, timeout)

        try:
            text = json.dumps(obj) + "\n"
            sock.sendall(text.encode("utf-8"))
            reader = sock.makefile(mode="r", encoding="utf-8", errors="replace")
            line = reader.readline()
            return json.loads(line)
        except (TimeoutError, OSError, ValueError):
            raise SERVICE_UNAVAILABLE
        finally:
            sock.close()
    
    # Similar to start_tcp_server but listening for peers instead
    def start_listener(self, host, port):
         # AF_INET for IPV4
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # REUSEADDR for reusing the same address when testing
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        # backlog
        sock.listen(10)

        print(f"[{self.id}] Peer listener on {host}:{port}")

        try:
            while True:
                conn, addr = sock.accept()
                peer_thread = threading.Thread(
                    target=self.handle_peer_connection,
                    args=(conn, addr),
                    daemon=True,
                )
                peer_thread.start()
        finally:
            sock.close()

    # PEER LISTENER SECTION
    # Heartbeat messages
    # methods will be defined later 
    def handle_peer_message(self, msg):
        message_type = msg["type"]

        if message_type == "PING":
            return "PONG", msg["sequence"]
        
        elif message_type == "FORWARD":
            return self.do_local_operation(msg)

        elif message_type == "REPLICATE":
            return self.store_replica(msg)

        elif message_type == "LEADER_ANNOUNCE":
            return self.update_leader(msg)
        elif message_type == "USER_ADD":
            return self.add_user(msg)
        else:
            raise SERVER_ERROR

    def handle_peer_connection(self, conn, addr):
        reader = conn.makefile(mode="r", encoding="utf-8", errors="replace")

        try:
            for line in reader:
                try:
                    msg = json.loads(line)
                except ValueError:
                    raise BAD_REQUEST("Peer message is not valid JSON.")
                if not isinstance(msg, dict):
                    raise BAD_REQUEST("Peer message must be a JSON object.")

                reply = self.handle_peer_message(msg)
                send_line(conn, reply)
        except TypeError:
            raise BAD_REQUEST()
        finally:
            reader.close()
            conn.close()
            
    # Heartbeats
    # Send a ping to each peer every 2 seconds
    # Wait up to two seconds for a matching PONG
    # count missing or timed-out repsonse as one missed heartbeat
    # mark a peer unavailable after 3 consecutive missed heartbeats
    # reset mssed-response counter after successful heartbeat
    # keep monitoring health peers after another peer fails 

    # likely this method needs to be moved inside a class to get self.id

    def heartbeat_loop(self, peer):
        seq = 0
        while True:
            seq += 1
            try:
                resp = self.peer_call(peer, {"type": "PING", "from": self.id, "sequence": seq})
                if resp["type"] == "PONG" and resp["sequence"] == seq:
                    self.misses[peer] = 0
                    self.alive[peer] = True
            finally:
                print("test")
        
    

    def do_local_operation(self, msg, **fields):
        pass

    def store_replica(self, msg):
        pass

    def update_leader(self, msg):
        pass

    def add_user(self, msg):
        pass

    def get_id(self):
        return self.id


# Creating a class for a Message object that contains relevant data 
class Message:
    def __init__(self, message_id, channel, username, text, timestamp):
        self.id = message_id
        self.channel = channel
        self.username = username
        self.text = text
        self.time = timestamp

    # get methods
    def get_id(self):
        return self.id

    def get_channel(self):
        return self.channel

    def get_username(self):
        return self.username

    def get_text(self):
        return self.text

    def get_timestamp(self):
        return self.time

    def to_dict(self):
        return {"message_id": self.id, "username": self.username, "text": self.text}




# Parent Class for Errors
# Inherits from Exception
class ERROR(Exception):
    # Defining default values
    code = "SERVER_ERROR"
    http_status = 500
    default_message = "An error occurred"

    def __init__(self, message=None):
        if message is None:
            self.message = self.default_message
        else:
            self.message = message

        super().__init__(self.message)

    def to_dict(self):
        json_dict = {"status": "error", "code": self.code, "message": self.message}

        return json_dict


# Subclasses below that inherit from ERROR, taken from PA1
class BAD_REQUEST(ERROR):
    code = "BAD_REQUEST"
    http_status = 400
    default_message = "A bad request was made."

class NOT_AUTHENTICATED(ERROR):
    code = "NOT_AUTHENTICATED"
    http_status = 401
    default_message = "Please log in first."

class CONFLICT(ERROR):
    code = "CONFLICT"
    http_status = 409
    default_message = "The resource already exists."

class INVALID_USERNAME(ERROR):
    code = "INVALID_USERNAME"
    http_status = 400
    default_message = "Invalid username, please try again. Usernames may contain only letters, digits, hyphens, and underscores."

class INVALID_CHANNEL(ERROR):
    code = "INVALID_CHANNEL"
    http_status = 400
    default_message = "Invalid channel name. Channels must start with # followed by letters, digits, hyphens or underscores."

class SERVER_ERROR(ERROR):
    code = "SERVER_ERROR"
    http_status = 500
    default_message = "Internal server error occurred."

class NOT_FOUND(ERROR):
    code = "NOT_FOUND"
    http_status = 404
    default_message = "The requested resource was not found."

# New error class regarding heartbeat-based failure detection
class SERVICE_UNAVAILABLE(ERROR):
    code = "SERVICE_UNAVAILABLE"
    http_status = 503
    default_message = "Peer process is not detected."

# mapping code to exception class for forwarding messages (5.2) 
code_to_class = {
    "BAD_REQUEST"         : BAD_REQUEST,
    "NOT_AUTHENTICATED"   : NOT_AUTHENTICATED,
    "CONFLICT"            : CONFLICT,
    "INVALID_USERNAME"    : INVALID_USERNAME,
    "INVALID_CHANNEL"     : INVALID_CHANNEL,
    "SERVER_ERROR"        : SERVER_ERROR,
    "NOT_FOUND"           : NOT_FOUND,
    "SERVICE_UNAVAILABLE" : SERVICE_UNAVAILABLE
}

# creating a method to handle fallback if an invalid code is entered
def code_lookup(code):
    try:
        return code_to_class[code]
    except KeyError:
        return code_to_class["SERVER_ERROR"]



# Class to define the DiscordServer
# Creating a threading HTTPServer that takes Store as an input
# inherits everything else
class MiniDiscordServer(http.server.ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, store: Store):
        super().__init__(server_address, RequestHandlerClass)
        self.store = store


class MiniDiscordHandler(http.server.BaseHTTPRequestHandler):

    def _send_json(self, status, obj):
        body = json.dumps(obj, separators=(",", ":")) + "\n"
        body_encoded = body.encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_encoded)))
        self.end_headers()
        self.wfile.write(body_encoded)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            # if the content length is negative
            if length < 0:
                raise BAD_REQUEST("Integer must be 0 or greater.")

        except ValueError:
            raise BAD_REQUEST("Not a number. Please enter an integer.")

        raw_text = self.rfile.read(length) if length else b""

        if raw_text:
            # pass raw text, do not replace any errors
            try:
                body_text = raw_text.decode("utf-8")
                parsed_text = json.loads(body_text)
            except ValueError:
                raise BAD_REQUEST("Failed to parse json")
        else:
            raise BAD_REQUEST("JSON request raw text was not found")

        if not isinstance(parsed_text, dict):
            raise BAD_REQUEST("JSON is not a dictionary")
        return parsed_text

    ## Helper method to get the X-User header
    def require_user_header(self):
        value = self.headers.get("X-User")
        if value is None:
            raise BAD_REQUEST("X-User is required.")

        value = value.strip() # remove leading and trailing whitespace
        if value == "":
            raise BAD_REQUEST("X-User header is empty")

        return value

    # Helper method to unquote segments
    def unquote_segments(self, segments):
        # unquote each segment
        for i, segment in enumerate(segments):
            segment = urllib.parse.unquote(segment)
            segments[i] = segment
        return segments
        
    def do_GET(self):
        try:
            store = self.server.store

            path = self.path

            # urlsplit returns separate parts (path, query), we are only interested in .path
            parsed_path = urllib.parse.urlsplit(path).path
            query = urllib.parse.urlsplit(path).query

            parsed_query = urllib.parse.parse_qs(query) # returns dict

            segments = parsed_path.split('/')

            segments = self.unquote_segments(segments)

            length = len(segments)
            if length == 2:
                if segments[1] == "health":
                    self._send_json(200, {"status": "ok"})

                elif segments[1] == "users":
                    self._send_json(200, {"users": store.get_users()})

                elif segments[1] == "channels":
                    self._send_json(200, {"channels": store.get_channels()})

                else:
                    raise NOT_FOUND("Unknown path.")

            elif length == 4:
                if segments[1] == "channels" and segments[3] == "users":
                    # verify last segment of GET query is users
                    channel = segments[2]
                    self._send_json(200, {"channel": channel, 
                                          "users" : store.get_users_of_channel(channel)})
                elif segments[1] == "channels" and segments[3] == "messages":
                    # get the limit parameter from the query section of path
                    # convert it to an int()
                    channel = segments[2]
                    try:
                        limit = int(parsed_query["limit"][0])
                        self._send_json(200, {"channel": channel,
                                               "messages":store.get_channel_history(channel, limit)})
                    except ValueError:
                        raise BAD_REQUEST("Limit parameter is not found or not an integer.")

                    except KeyError:
                        self._send_json(200, {"channel": channel,
                                                                  "messages":store.get_channel_history(channel)})
                        
                else:
                    raise NOT_FOUND("Unknown path.")
            else:
                raise NOT_FOUND("Unknown path.")

        except ERROR as e:
            self._send_json(e.http_status, e.to_dict())
        except Exception:
            traceback.print_exc()
            self._send_json(500, SERVER_ERROR().to_dict())

    def do_POST(self):
        try:
            store = self.server.store

            path = self.path

            # urlsplit returns separate parts, we are only interested in .path
            parsed_path = urllib.parse.urlsplit(path).path
            
            segments = parsed_path.split('/')
            
            segments = self.unquote_segments(segments)

            length = len(segments)

            if length == 2:
                if segments[1] == "users":
                    body = self._read_json()
                    name = body.get("username")

                    # name should be of type str, this rejects None values as well
                    if not isinstance(name, str):
                        raise BAD_REQUEST("Name is invalid")
                    store.register_user(name)
                    self._send_json(201, {"username": name})
                else:
                    raise NOT_FOUND("Unknown path.")
            elif length == 4:

                if segments[1] == "channels" and segments[3] == "members":
                    channel = segments[2]
                    username = self.require_user_header()
                    store.join(username, channel)
                    self._send_json(200, {"channel": channel,
                                        "username": username,
                                        "joined": True})

                elif segments[1] == "channels" and segments[3] == "messages":
                    channel = segments[2]
                    username = self.require_user_header()

                    
                    body = self._read_json()
                    text = body.get("text")
                    if not isinstance(text, str):
                        raise BAD_REQUEST("Text/message is invalid.")

                    if text == "":
                        raise BAD_REQUEST("Message is empty.")
                    
                    message = store.post_message(channel, username, text)
                    message_id = message.get_id()
                    self._send_json(201, {"message_id" : message_id,
                                          "channel": channel,
                                          "username": username,
                                          "text": text})

                else:
                    raise NOT_FOUND("Unknown path.")
            else:
                raise NOT_FOUND("Unknown path.")
        except ERROR as e:
            self._send_json(e.http_status, e.to_dict())
        except Exception:
            traceback.print_exc()
            self._send_json(500, SERVER_ERROR().to_dict())

    def do_DELETE(self):
        try:
            store = self.server.store
            path = self.path

            # urlsplit returns separate parts, we are only interested in .path
            parsed_path = urllib.parse.urlsplit(path).path

            segments = parsed_path.split('/')
            
            segments = self.unquote_segments(segments)

            length = len(segments)
            
            if length == 5:
                if segments[1] == "channels" and segments[3] == "members":
                    channel = segments[2]
                    username = segments[4]
                    store.leave(username, channel)

                    self._send_json(200, {"channel": channel,
                                        "username": username,
                                        "left": True})
                else:
                    raise NOT_FOUND("Unknown path.")
            else:
                raise NOT_FOUND("Not a proper DELETE request.")
        except ERROR as e:
            self._send_json(e.http_status, e.to_dict())
        except Exception:
            traceback.print_exc()
            self._send_json(500, SERVER_ERROR().to_dict())
    # Return None, simply print
    def log_message(self, format, *args):
        print(format % args)


# Function to start the TCP server
def start_tcp_server(host, port, store):
    # AF_INET for IPV4
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # REUSEADDR for reusing the same address when testing
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    # backlog
    sock.listen(10)

    print(f"TCP listening on {host}:{port}")

    try:
        while True:
            conn, addr = sock.accept()
            print(f"New client has joined from {addr}")
            
            tcp_thread = threading.Thread(target=handle_tcp_client, args=(conn, addr, store), daemon=True)
            tcp_thread.start()
    finally:
        sock.close()

def handle_tcp_client(conn, addr, store):
    user = None
    should_close = False
    reader = conn.makefile(mode="r", encoding="utf-8", errors="replace")
    
    try:
        for line in reader:
            response, should_close, user = process_line(line, user, store)
            send_line(conn, response)
            if should_close:
                break

    except OSError as e:
        print(e, addr)

    finally:
        try: 
            if should_close:
                print(f"Client {addr} quit cleanly.")
            else:
                print(f"Client {addr} disconnected unexpectedly (User: {user})")
            if user is not None:
                 store.remove_user_from_channels(user)
        finally:
            reader.close()
            conn.close()

def process_line(line, user, store):
    try:
        line = line.strip()
        if line == "":
            raise BAD_REQUEST("Empty command. No line to process")

        tokens = line.split(maxsplit=2)

        cmd = tokens[0].upper()

        if cmd == "REGISTER":    return tcp_register(tokens, user, store)
        elif cmd == "LOGIN":     return tcp_login(tokens, user, store)
        elif cmd == "JOIN":      return tcp_join(tokens, user, store)
        elif cmd == "LEAVE":     return tcp_leave(tokens, user, store)
        elif cmd == "SEND":      return tcp_send(tokens, user, store)
        elif cmd == "LIST":      return tcp_list(tokens, user, store)
        elif cmd == "HISTORY":   return tcp_history(tokens, user, store)
        elif cmd == "LOGOUT":    return tcp_logout(tokens, user, store)
        elif cmd == "QUIT":      return tcp_quit(tokens, user, store)
        else:
            raise BAD_REQUEST(f"Unknown command: {cmd}")

    except ERROR as e:
        return e.to_dict(), False, user

    except Exception:
        traceback.print_exc()
        return SERVER_ERROR().to_dict(), False, user


def send_line(conn, obj):
    text = json.dumps(obj, separators=(",", ":")) + "\n"
    conn.sendall(text.encode("utf-8"))
    
# helper methods of process_line for TCP part
def require_login(user):
    if user is None:
        raise NOT_AUTHENTICATED("Not logged in. Use LOGIN <username> first to log in.")
    return user

# number of tokens for tcp command
# allowed_counts is a set() which is for LIST and HISTORY commands, which can take 2 or 3 tokens
def require_args(tokens, allowed_counts, usage):
    if len(tokens) not in allowed_counts:
        raise BAD_REQUEST("Usage: " + usage)


def tcp_register(tokens, user, store):
    require_args(tokens, {2}, "REGISTER <username>")
    store.register_user(tokens[1])
    return {"status": "ok",
                        "operation": "register",
                        "username": tokens[1]}, False, user

def tcp_login(tokens, user, store):
    require_args(tokens, {2}, "LOGIN <username>")
    if not store.is_user(tokens[1]):
        raise NOT_FOUND("User is not found. Please register if needed or try again.")

    return {"status": "ok",
                "operation": "login",
                "username": tokens[1]}, False, tokens[1]


def tcp_join(tokens, user, store):
    require_args(tokens, {2}, "JOIN <channel>")
    name = require_login(user)
    store.join(name, tokens[1])
    return {"status": "ok",
                        "operation": "join",
                        "channel": tokens[1],
                        "username": name}, False, user

def tcp_leave(tokens, user, store):
    require_args(tokens, {2}, "LEAVE <channel>")
    name = require_login(user)
    store.leave(name, tokens[1])
    return {"status": "ok",
                            "operation": "leave",
                            "channel": tokens[1],
                            "username": name}, False, user

def tcp_send(tokens, user, store):
    require_args(tokens, {3}, "SEND <channel> <text>")
    name = require_login(user)
    message = store.post_message(tokens[1], name, tokens[2])

    return {"status": "ok",
            "operation": "send",
            "message_id": message.get_id()}, False, user

def tcp_list(tokens, user, store):
    require_args(tokens, {2, 3}, "LIST CHANNELS | LIST USERS <channel>")
    subcmd = tokens[1].upper()

    if subcmd == "CHANNELS" and len(tokens) == 2:
        channels = store.get_channels()
        return {"status": "ok",
                    "operation": "list_channels",
                    "channels": channels}, False, user
    elif subcmd == "USERS" and len(tokens) == 3:
        users = store.get_users_of_channel(tokens[2])
        return {"status": "ok",
                            "operation": "list_users",
                            "channel": tokens[2],
                            "users": users}, False, user
    else:
        raise BAD_REQUEST("Bad request. Please try again with proper format.")

def tcp_history(tokens, user, store):
    require_args(tokens, {2,3}, "HISTORY <channel> [limit]")

    if len(tokens) == 2:
        # default limit
        history = store.get_channel_history(tokens[1])
        return {"status": "ok",
                                "operation": "history",
                                "channel": tokens[1],
                                "messages": history}, False, user
    elif len(tokens) == 3:
        try: 
            limit = int(tokens[2])
            history = store.get_channel_history(tokens[1], limit)
            return {"status": "ok",
                    "operation": "history",
                    "channel": tokens[1],
                    "messages": history}, False, user
        except ValueError:
            raise BAD_REQUEST("Limit is not an integer.")

def tcp_logout(tokens, user, store):
    require_args(tokens, {1}, "LOGOUT")
    name = require_login(user)
    store.remove_user_from_channels(name)
    return {"status": "ok",
            "operation": "logout",
            "username": name}, False, None
    
def tcp_quit(tokens, user, store):
    require_args(tokens, {1}, "QUIT")
    return {"status": "ok",
            "operation": "quit"}, True, user

# defining a helper method for passing failures
def fail(message) -> NoReturn:
    sys.exit("config failed for: " + message)

# looks for the obj in path
def load_config(path):
    try:
        # read the servers.json file and load the json object
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

            if not isinstance(raw, dict):
                fail("Config must be a JSON object")

            if "servers" not in raw:
                fail("Config does not contain servers list.")

            if "channels" not in raw:
                fail("Config does not contain channels list.")

            # if it reaches this point, raw file is of the right format
            # Create dictionary with servers mapping id to server details
            # and channels mapping primary server to backup server
            servers = {}
            channels = {}

            for server in raw["servers"]:
                for field in ["id", "host", "http_port", "peer_port", "priority"]:
                    # check if servers.json has all fields
                    if field not in server:
                        fail("Server is missing field " + field + ".")
                if server["id"] in servers:
                        fail("Entry is already in servers list.")

                # Can add server to servers dict at this point
                servers.update({server["id"]: {
                        "host": server["host"],
                        "http_port": server["http_port"],
                        "peer_port": server["peer_port"],
                        "priority": server["priority"],
                        }})

            for channel in raw["channels"]:
                for field in ["channel", "primary", "backup"]:

                    if field not in channel:
                        fail("Channel is missing field " + field + ".")

                if channel["channel"] in channels:
                        fail("Entry is already in channels list.")

                    # can add channel to channels dict at this point
                channels.update({channel["channel"]: {
                    "primary": channel["primary"],
                    "backup": channel["backup"],
                }})
        config = {"servers": servers, "channels": channels}

        validate_config(config)
        return config
    
    except FileNotFoundError:
        fail("The file at the path does not exist.")
    except ValueError:
        fail("The file could not be read as UTF-8 JSON.")
    

def validate_config(config):
    servers = config["servers"]
    channels = config["channels"]
    regex_channel = re.compile("^#[A-Za-z0-9_-]+$")

    if len(servers) != 3:
        fail("Did not find the expected count of 3 servers.")

    # grabbing server id and the dictionary associated with it
    for id, key in servers.items():
        # if host does not exist as a string
        if not key["host"]:
            fail(id + ": bad host")

        # if ports and priority are not integers
        if not all(isinstance(item, int) for item in [key["http_port"], key["peer_port"], key["priority"]]):
            fail(id + ": ports and priority must all be integers.")

        ports = [key["http_port"], key["peer_port"]]

        # if ports are not within the right range of ports
        if any(port not in range(1,65536) for port in ports):
            fail(id + ": port out of range")

        # if the two ports are equal to one another
        if ports[0] == ports[1]:
            fail(id + ": http port and peer port are matching.")


    # if there are no channels
    if len(channels) == 0:
        fail("No channels defined.")

    for channel, key in channels.items():

        primary = key["primary"]
        backup = key["backup"]

        # if channel name format is not followed
        if not regex_channel.search(channel):
            fail("invalid channel name: " + channel)

        if primary not in servers:
            fail("Unknown primary id for: " + channel)

        if backup not in servers:
            fail("Unknown backup id for: " + channel)

        if primary == backup:
            fail(channel + ": primary and backup are both " + primary)
    





def main():
    
    parser = argparse.ArgumentParser()
    # -- config
    parser.add_argument("--config", help="Specify servers.json file here")
    parser.add_argument("--id", help="id should be extracted from config file")
    args = parser.parse_args()

    config = load_config(args.config)  
    if args.id not in config["servers"]:
        fail("Server ID not found.")

    server = config["servers"][args.id]
    all_channels = config["channels"]

    server_id = args.id
    server_host = server["host"]
    server_http_port = server["http_port"]
    server_peer_port = server["peer_port"]

    store = Store(list(all_channels))
    peer = Peer(server_id, store, config)
    
    # Creating the HTTP thread
    httpd = MiniDiscordServer((server_host, server_http_port), MiniDiscordHandler, store)

    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    print(f"HTTP Thread started on {server_host}:{server_http_port}")

    # Creating the TCP server
    try:
        peer.start_listener(server_host, server_peer_port)
    except KeyboardInterrupt:
        print("Shutting down TCP server")
        # At this point, the daemon should die with the server but add finally for good measure
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
