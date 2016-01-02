#!/usr/bin/env python

from __future__ import with_statement
from __future__ import absolute_import
from __future__ import print_function

import os
import sys
import json
import logging
import datetime
import functools

# python 2 and 3 compatibility
try:
    basestring  # attempt to evaluate basestring
    def isstr(s):
        return isinstance(s, basestring)
except NameError:
    def isstr(s):
        return isinstance(s, str)

from simpletraj import trajectory

from flask import Flask
from flask import send_from_directory
from flask import request
from flask import make_response, Response
from flask import current_app

logging.basicConfig( level=logging.DEBUG )
LOG = logging.getLogger('ngl')
LOG.setLevel( logging.DEBUG )

cfg_file = 'app.cfg'
app = Flask(__name__)
app.config.from_pyfile( cfg_file )

MODULE_DIR = os.path.split( os.path.abspath( __file__ ) )[0]


############################
# basic auth
############################

def check_auth( auth ):
    """This function is called to check if a username /
    password combination is valid.
    """
    return (
        auth.username == app.config.get( 'USERNAME', '' ) and
        auth.password == app.config.get( 'PASSWORD', '' )
    )


def check_data_auth( auth, root ):
    if root in DATA_AUTH:
        return (
            auth.username == DATA_AUTH[ root ][ 0 ] and
            auth.password == DATA_AUTH[ root ][ 1 ]
        )
    else:
        return True


def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials', 401,
        { 'WWW-Authenticate': 'Basic realm="Login Required"' }
    )


# use as decorator *after* a route decorator
def requires_auth( f ):
    @functools.wraps( f )
    def decorated( *args, **kwargs ):
        REQUIRE_AUTH = app.config.get( 'REQUIRE_AUTH', False )
        REQUIRE_DATA_AUTH = \
            app.config.get( 'REQUIRE_DATA_AUTH', False ) and not REQUIRE_AUTH
        DATA_AUTH = app.config.get( 'DATA_AUTH', {} )
        auth = request.authorization
        root = kwargs.get( "root", None )
        if REQUIRE_AUTH:
            if not auth or not check_auth( auth ):
                return authenticate()
        elif REQUIRE_DATA_AUTH and root and root in DATA_AUTH:
            if not auth or not check_data_auth( auth, root ):
                return authenticate()
        return f( *args, **kwargs )
    return decorated


####################
# helper functions
####################

def get_directory( root ):
    DATA_DIRS = app.config.get( "DATA_DIRS", {} )
    if root in DATA_DIRS:
        directory = os.path.join( DATA_DIRS[ root ] )
        return os.path.abspath( directory )
    else:
        return ""


def crossdomain(
    origin=None, methods=None, headers=None,
    max_age=21600, attach_to_all=True, automatic_options=True
):
    if methods is not None:
        methods = ', '.join( sorted( x.upper() for x in methods ) )
    if headers is not None and not isstr( headers ):
        headers = ', '.join( x.upper() for x in headers )
    if not isstr( origin ):
        origin = ', '.join(origin)
    if isinstance( max_age, datetime.timedelta ):
        max_age = max_age.total_seconds()

    def get_methods():
        if methods is not None:
            return methods

        options_resp = current_app.make_default_options_response()
        return options_resp.headers[ 'allow' ]

    def decorator(f):
        def wrapped_function(*args, **kwargs):
            if automatic_options and request.method == 'OPTIONS':
                resp = current_app.make_default_options_response()
            else:
                resp = make_response( f( *args, **kwargs ) )
            if not attach_to_all and request.method != 'OPTIONS':
                return resp
            h = resp.headers
            h['Access-Control-Allow-Origin'] = origin
            h['Access-Control-Allow-Methods'] = get_methods()
            h['Access-Control-Max-Age'] = str( max_age )
            if headers is not None:
                h['Access-Control-Allow-Headers'] = headers
            return resp
        f.provide_automatic_options = False
        return functools.update_wrapper( wrapped_function, f )
    return decorator


###############
# web app
###############

@app.route( '/webapp/' )
@app.route( '/webapp/<path:filename>' )
@requires_auth
@crossdomain( origin='*' )
def webapp( filename="index.html" ):
    directory = os.path.join( MODULE_DIR, "webapp" )
    return send_from_directory( directory, filename )


###############
# file server
###############

@app.route( '/file/<root>/<path:filename>' )
@requires_auth
@crossdomain( origin='*' )
def file( root, filename ):
    directory = get_directory( root )
    if directory:
        return send_from_directory( directory, filename )


@app.route( '/dir/' )
@app.route( '/dir/<root>/' )
@app.route( '/dir/<root>/<path:path>' )
@requires_auth
@crossdomain( origin='*' )
def dir( root="", path="" ):
    DATA_DIRS = app.config.get( "DATA_DIRS", {} )
    REQUIRE_AUTH = app.config.get( 'REQUIRE_AUTH', False )
    REQUIRE_DATA_AUTH = \
        app.config.get( 'REQUIRE_DATA_AUTH', False ) and not REQUIRE_AUTH
    DATA_AUTH = app.config.get( 'DATA_AUTH', {} )
    if sys.version_info < (3,):
        root = root.encode( "utf-8" )
        path = path.encode( "utf-8" )
    dir_content = []
    if root == "":
        for fname in DATA_DIRS.keys():
            if sys.version_info < (3,):
                fname = unicode( fname )
            if fname.startswith( '_' ):
                continue
            dir_content.append({
                'name': fname,
                'path': fname,
                'dir': True,
                'restricted': REQUIRE_DATA_AUTH and fname in DATA_AUTH
            })
        return json.dumps( dir_content )
    directory = get_directory( root )
    if sys.version_info < (3,):
        directory = directory.encode( "utf-8" )
    if not directory:
        return json.dumps( dir_content )
    dir_path = os.path.join( directory, path )
    if path == "":
        dir_content.append({
            'name': '..',
            'path': "",
            'dir': True
        })
    else:
        dir_content.append({
            'name': '..',
            'path': os.path.split( os.path.join( root, path ) )[0],
            'dir': True
        })
    for fname in sorted( os.listdir( dir_path ) ):
        if sys.version_info < (3,):
            fname = fname.decode( "utf-8" ).encode( "utf-8" )
        if( not fname.startswith('.') and
                not ( fname.startswith('#') and fname.endswith('#') ) ):
            fpath = os.path.join( dir_path, fname )
            if os.path.isfile( fpath ):
                dir_content.append({
                    'name': fname,
                    'path': os.path.join( root, path, fname ),
                    'size': os.path.getsize( fpath )
                })
            else:
                dir_content.append({
                    'name': fname,
                    'path': os.path.join( root, path, fname ),
                    'dir': True
                })
    for fname in trajectory.get_split_xtc( dir_path ):
        if sys.version_info < (3,):
            fname = fname.decode( "utf-8" ).encode( "utf-8" )
        dir_content.append({
            'name': fname,
            'path': os.path.join( root, path, fname ),
            'size': sum([
                os.path.getsize( x ) for x in
                trajectory.get_xtc_parts( fname, dir_path )
            ])
        })
    return json.dumps( dir_content )


#####################
# trajectory server
#####################

TRAJ_CACHE = trajectory.TrajectoryCache()

@app.route( '/traj/frame/<int:frame>/<root>/<path:filename>', methods=['POST'] )
@requires_auth
@crossdomain( origin='*' )
def traj_frame( frame, root, filename ):
    directory = get_directory( root )
    if directory:
        path = os.path.join( directory, filename )
    else:
        return
    atom_indices = request.form.get( "atomIndices" )
    if atom_indices:
        atom_indices = [
            [ int( y ) for y in x.split( "," ) ]
            for x in atom_indices.split( ";" )
        ]
    return TRAJ_CACHE.get( path ).get_frame_string(
        frame, atom_indices=atom_indices
    )


@app.route( '/traj/numframes/<root>/<path:filename>' )
@requires_auth
@crossdomain( origin='*' )
def traj_numframes( root, filename ):
    directory = get_directory( root )
    if directory:
        path = os.path.join( directory, filename )
    else:
        return
    return str( TRAJ_CACHE.get( path ).numframes )


@app.route( '/traj/path/<int:index>/<root>/<path:filename>', methods=['POST'] )
@requires_auth
@crossdomain( origin='*' )
def traj_path( index, root, filename ):
    directory = get_directory( root )
    if directory:
        path = os.path.join( directory, filename )
    else:
        return
    frame_indices = request.form.get( "frameIndices" )
    if frame_indices:
        frame_indices = None
    return TRAJ_CACHE.get( path ).get_path_string(
        index, frame_indices=frame_indices
    )


############################
# main
############################

def open_browser( app, host, port, struc=None, traj=None ):
    if not app.config.get( "BROWSER_OPENED", False ):
        import webbrowser
        url = "http://" + host + ":" + str(port) + "/webapp"
        if struc:
            url += "?struc=file://current_dir/" + struc
            if traj:
                url += "&traj=file://current_dir/" + traj
        webbrowser.open( url, new=2, autoraise=True )
        app.config.BROWSER_OPENED = True


# based on http://stackoverflow.com/a/27598916
def patch_socket_bind( on_bind ):
    try:
        import socketserver
    except ImportError:
        import SocketServer as socketserver
    original_socket_bind = socketserver.TCPServer.server_bind
    def socket_bind_wrapper(self):
        ret = original_socket_bind(self)
        if on_bind:
            host, port = self.socket.getsockname()
            on_bind( host, port )
        # Recover original implementation
        socketserver.TCPServer.server_bind = original_socket_bind
        return ret
    socketserver.TCPServer.server_bind = socket_bind_wrapper

def parse_args():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument( 'struc', type=str, nargs='?', default="" )
    parser.add_argument( 'traj', type=str, nargs='?', default="" )
    args = parser.parse_args()
    return args

def entry_point():
    DATA_DIRS = app.config.get( "DATA_DIRS", {} )
    DATA_DIRS.update( {
        "current_dir": os.path.abspath( os.getcwd() ),
        "example_data": os.path.join( MODULE_DIR, "data" ),
    } )
    app.config[ "DATA_DIRS" ] = DATA_DIRS
    args = parse_args()
    def on_bind( host, port ):
        open_browser( app, host, port, args.struc, args.traj )
    patch_socket_bind( on_bind )
    main()

def main():
    app.run(
        debug=app.config.get( 'DEBUG', False ),
        host=app.config.get( 'HOST', '127.0.0.1' ),
        port=app.config.get( 'PORT', 8010 ),
        threaded=True,
        processes=1
    )

if __name__ == '__main__':
    main()
