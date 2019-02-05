from mysmb import MYSMB
from impacket import smb, smbconnection, nt_errors
from impacket.uuid import uuidtup_to_bin
from impacket.dcerpc.v5.rpcrt import DCERPCException
from struct import pack
import sys
import argparse
import logger
from ip_parser import parse_targets,from_file

'''
Script for
- check target if MS17-010 is patched or not.
- find accessible named pipe
'''


parser = argparse.ArgumentParser(description='MS17-010 Checker script',epilog="Example: python checker.py -t 192.168.0.1-100")
parser.add_argument("-u", "--user", type=str, metavar="",help="Username to authenticate with")
parser.add_argument("-p", "--password", type=str, metavar="",help="Password for specified user")
parser.add_argument("-t", "--target", type=str, metavar="", help="Target (IP, range, CIDR) to check for MS17-010")
parser.add_argument("-tf", "--target-file", type=str, metavar="", help="Target (IP, range, CIDR) to check for MS17-010")
parser.add_argument('--version', action='version', version='%(prog)s 0.1')
args = parser.parse_args()


if args.user:
	USERNAME = args.user
else:
	USERNAME = ''

if args.user:
	PASSWORD = args.password
else:
	PASSWORD = ''


NDR64Syntax = ('71710533-BEBA-4937-8319-B5DBEF9CCC36', '1.0')

MSRPC_UUID_BROWSER  = uuidtup_to_bin(('6BFFD098-A112-3610-9833-012892020162','0.0'))
MSRPC_UUID_SPOOLSS  = uuidtup_to_bin(('12345678-1234-ABCD-EF00-0123456789AB','1.0'))
MSRPC_UUID_NETLOGON = uuidtup_to_bin(('12345678-1234-ABCD-EF00-01234567CFFB','1.0'))
MSRPC_UUID_LSARPC   = uuidtup_to_bin(('12345778-1234-ABCD-EF00-0123456789AB','0.0'))
MSRPC_UUID_SAMR     = uuidtup_to_bin(('12345778-1234-ABCD-EF00-0123456789AC','1.0'))

pipes = {
	'browser'  : MSRPC_UUID_BROWSER,
	'spoolss'  : MSRPC_UUID_SPOOLSS,
	'netlogon' : MSRPC_UUID_NETLOGON,
	'lsarpc'   : MSRPC_UUID_LSARPC,
	'samr'     : MSRPC_UUID_SAMR,
}

def ms17_010(target):
	try:
		logger.info('Attempting to connect to: {}'.format(logger.BLUE(target)))
		conn = MYSMB(target, timeout=5)
		try:
			conn.login(USERNAME, PASSWORD)
		except smb.SessionError as e:
			logger.error('Login failed, got error: ' + logger.RED(nt_errors.ERROR_MESSAGES[e.error_code][0]))
			sys.exit()
		finally:
			logger.info('Found target OS: ' + logger.BLUE(conn.get_server_os()))

		tid = conn.tree_connect_andx('\\\\' + target + '\\' + 'IPC$')
		conn.set_default_tid(tid)

		# test if target is vulnerable
		TRANS_PEEK_NMPIPE = 0x23
		recvPkt = conn.send_trans(pack('<H', TRANS_PEEK_NMPIPE), maxParameterCount=0xffff, maxDataCount=0x800)
		status = recvPkt.getNTStatus()
		if status == 0xC0000205:  # STATUS_INSUFF_SERVER_RESOURCES
			logger.success('{} IS NOT PATCHED!'.format(logger.GREEN(target)))
		else:
			logger.error('{} IS PATCHED!'.format(logger.RED(target)))
			sys.exit()

		logger.action('Looking for the named pipes...')
		for pipe_name, pipe_uuid in pipes.items():
			try:
				dce = conn.get_dce_rpc(pipe_name)
				dce.connect()
				try:
					dce.bind(pipe_uuid, transfer_syntax=NDR64Syntax)
					logger.success('{}: OK (64 bit)'.format(logger.GREEN(pipe_name)))
				except DCERPCException as e:
					if 'transfer_syntaxes_not_supported' in str(e):
						logger.success('{}: OK (32 bit)'.format(logger.GREEN(pipe_name)))
					else:
						logger.success('{}: OK ({})'.format(logger.GREEN(pipe_name), str(e)))
				dce.disconnect()
			except smb.SessionError as e:
				logger.error('{}: {}'.format(logger.RED(pipe_name), logger.RED(nt_errors.ERROR_MESSAGES[e.error_code][0])))
			except smbconnection.SessionError as e:
				logger.error('{}: {}'.format(logger.RED(pipe_name), logger.RED(nt_errors.ERROR_MESSAGES[e.error][0])))

		conn.disconnect_tree(tid)
		conn.logoff()
		conn.get_socket().close()
	except (KeyboardInterrupt, SystemExit):
		logger.error('Keyboard interrupt received..')
		sys.exit(-1)
	except:
		logger.error('Connection failed to: {}'.format(logger.RED(str(target))))


if args.target != None and args.target_file == None:
	for target in parse_targets(args.target):
		ms17_010(target)

elif args.target == None and args.target_file != None:
	for target in from_file(args.target_file):
		ms17_010(target)
