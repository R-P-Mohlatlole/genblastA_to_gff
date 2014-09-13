#!/usr/bin/env python

import argparse
import sys
import re
import logging
import logging.config
import json
import os

START_STR = '//*****************START'
END_STR = '//******************END'
QUERY_NAME_STR = '//for query: '
HSP_STR = 'HSP_ID'
GENOMIC_MATCH_RE = re.compile('^(?P<query_name>[^|]*)\|(?P<match_name>[^:]*):(?P<match_start>\d+)\.\.(?P<match_end>\d+)\|(?P<strand>[+-])\|gene cover:(?P<coverage_num>\d+)\((?P<coverage_perc>[\d.]+)%\)\|score:(?P<score>[-\d.]+)\|rank:(?P<rank>\d+)$')
HSP_RE = re.compile('^HSP_ID\[(?P<hsp_id>\d+)\]:\((?P<match_start>\d+)-(?P<match_end>\d+)\);query:\((?P<query_start>\d+)-(?P<query_end>\d+)\); pid: (?P<perc_id>[\d.]+)$')

def parse_genblastA(input_filename):
	in_record = False
	# variables set during parsing
	hsp_dict = dict()
	genomic_match = None
	query_name = ''
	for line in input_filename:
		if not in_record:
			if line.startswith(START_STR):
				in_record = True
		else:
			# we're in a record
			if line.startswith(END_STR):
				# check that we've got a match to output (we might have NONE)
				if genomic_match:
					yield(dict(match=genomic_match, hsps=hsp_dict))
				hsp_dict = dict()
				genomic_match = None
				query_name = ''
				in_record = False
			elif line.startswith(QUERY_NAME_STR):
				fields = line.split()
				if len(fields) != 4:
					logging.error('Got wrong number of fields ({} vs 4) in line: {}'.format(len(fields), line))
					in_record = False
				else:
					query_name = fields[2]
			elif 'gene cover' in line:
				if genomic_match:
					# we've already seen one match, need to output that
					yield(dict(match=genomic_match, hsps=hsp_dict))
					# and reset the hsp_dict, we're about to reset the genomic_match
					hsp_dict = dict()
				genomic_match = GENOMIC_MATCH_RE.match(line.rstrip())
				if not genomic_match:
					logging.error('Genomic match regexp failed to match on line: {}'.format(line))
					in_record = False
				else:
					# not much to do: we've got a genomic match saved in genomic_match, will use it once we've read the HSPs
					logging.debug('Got match between {} and {} start: {} end: {}'.format(genomic_match.group('query_name'), 
								  genomic_match.group('match_name'), genomic_match.group('match_start'), genomic_match.group('match_end')))
			elif line.startswith(HSP_STR):
				match = HSP_RE.match(line.rstrip())
				if not match:
					logging.error('HSP regexp failed to match on line: {}'.format(line))
					in_record = False
				else:
					# save the HSPs for this genomic match
					hsp = dict(match_start=int(match.group('match_start')), match_end=int(match.group('match_end')), 
						       query_start=int(match.group('query_start')), query_end=int(match.group('query_end')), 
						       perc_id=float(match.group('perc_id')))
					hsp_dict[int(match.group('hsp_id'))] = hsp

def write_gff_line(genomic_match, hsp_dict, query_name, output_file):
	# gff3 format
	# seq source type start end score strand phase attributes"
	num_hsps = len(hsp_dict)
	match_length = abs(int(genomic_match.group('match_end')) - int(genomic_match.group('match_start')))
	avg_perc_identity = sum([hsp_dict[i]['perc_id'] for i in hsp_dict])/num_hsps
	query_coverage_perc = float(genomic_match.group('coverage_perc'))
	if (avg_perc_identity >= args.min_perc_identity and
		query_coverage_perc >= args.min_perc_coverage and
		match_length >= args.min_match_length):
		attributes='ID={}_{}'.format(query_name, genomic_match.group('rank'))
		gff_line = '\t'.join([genomic_match.group('match_name'), 'BLAST', 'match',
							  genomic_match.group('match_start'), genomic_match.group('match_end'),
							  genomic_match.group('score'), genomic_match.group('strand'),
							  '.', attributes]) + '\n'
		output_file.write(gff_line)

log_config = os.getenv('LOG_CONFIG', None)
if log_config:
	log_config_file = None
	try:
		log_config_file = open(log_config)
	except IOError as e:
		sys.stderr.write('Failed to load logging config from {}: {}\n'.format(log_config, str(e)))
	if log_config_file:
		config_dict = json.load(log_config_file)
		try:
			logging.config.dictConfig(config_dict)
		except (ValueError, TypeError, AttributeError, ImportError) as e:
			sys.stderr.write('Failed to parse log config dictionary: {}\n'.format(str(e)))
			logging.basicConfig(level=logging.INFO)

parser = argparse.ArgumentParser(description='parse genblastA output and produce GFF3')
parser.add_argument('--min_perc_coverage','-C', type=float, default=80.0, help='Minimum coverage of the query sequence')
parser.add_argument('--min_match_length','-L', type=int, default=100, help='Shortest match length to accept')
parser.add_argument('--min_perc_identity','-I', type=float, default=80.0, help='Minimum average % identity to accept')
parser.add_argument('genblastA_file', type=argparse.FileType(), help='genblastA format file')
parser.add_argument('gff_file', nargs='?', type=argparse.FileType('w'), default=sys.stdout, help='GFF3 output file')
args = parser.parse_args()

args.gff_file.write('##gff-version 3\n')
for match in parse_genblastA(args.genblastA_file):
	write_gff_line(match['match'], match['hsps'], match['match'].group('query_name'), args.gff_file)
