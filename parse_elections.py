# -*- coding: utf-8 -*-

import os
from models import *
from model_helpers import parse_name, get_or_create_person, get_party
from model_helpers import get_or_create_source_doc
import re
import io
import inspect

f_path = 'source_docs/SoS/election_results/txts/'

# select the race_types into a list of matching purposes
race_types = []

for race_type in Race_Type.select():
	race_types.append(race_type)

# election date pattern
date_pattern = re.compile("^\s*(\w+,\s\w+\s\d{2},\s\d{4})$")

# candidate match pattern
cand_pattern = re.compile("^\s+(\w[\w\.\s,\xad'\(\)]+)\s{2,}([A-Za-z\d]{2,3})\s+([\d,]+)\s+([\d\.%]+)\s*$")

elections = []

# loop over the election results .txt files...
for i in os.listdir(f_path):
	# skipping any file without the .txt extension
	if '.txt' in i:

		print 'Getting data from {}'.format(i)

		# set up an election for each file
		election = Election(
			  date = None
			, races = []
		)

		# this particular election was not available in pdf
		# had to copy the text from the 2001 Blue Book
		if i == 'AllRacesSpecialMarch2000SD5.txt':
			election.source_doc = get_or_create_source_doc(
					  name = 'All Races Special March 2000 SD5'
					, file_name = f_path + i
					, url = 'http://s1.sos.mo.gov/cmsimages/bluebook/2001-2002/0711-0717.pdf#p715'
					, parent = None
				)
		else:
			source_doc_file = f_path + i
			election.source_doc = Source_Doc.get(Source_Doc.file_name == source_doc_file.replace('txt', 'pdf'))

		# determine which type of election it is (based on file name)
		for elec_type in Election_Type.select():
			if elec_type.name in i:
				election.election_type = elec_type

		# open the file
		with io.open(f_path + i, mode = 'r', encoding='UTF-8') as f:

			# declare a line reader so that we can reference line numbers (i.e., index position)
			reader = f.readlines()
			
			# for each line in the file
			for idx, line in enumerate(reader):

				# ignore lines with only one non-whitespace character
				if len(line.strip()) > 1:

					date_match = re.match(date_pattern, line)
					cand_match = re.match(cand_pattern, line)

					# if the line matches the election date pattern...
					if date_match != None:

	 					# set this election attribute
						election.election_date = date_match.group(1)

						# if it's a general election...
						if election.election_type.name == 'General':
							# assume it's for the assembly starting next year
							election.assembly = Assembly.get(start_year = int(re.search('\d{4}', election.election_date).group()) + 1)
						# if it's a special election...
						elif election.election_type.name == 'Special':
							try: 
								# first, try getting an assembly that started the same year...
								election.assembly = Assembly.get(start_year = int(re.search('\d{4}', election.election_date).group()))
							except Assembly.DoesNotExist: 
								# then try getting an assembly that ended the same year...
								election.assembly = Assembly.get(end_year = int(re.search('\d{4}', election.election_date).group()))

					elif 'State of Missouri' in line:

						election.name = line.replace('State of Missouri', '').strip()

	 				# see if any of the race types names are in the line
					elif any(race_type.name in line for race_type in race_types):

						# if so, then set up a new race
						race = Race(
							  candidates = []
							, total_votes = None
						)

						# set which type of race it is
						for race_type in race_types:
							if race_type.name in line:
								# then set this attribute
								race.race_type = race_type.id

						# if the candidate line also contains the word 'District'...
						if 'District' in line:
							# try finding the district number and setting this attribute
							try:
								race.district = re.search('\d+', line).group()
							except AttributeError:
								print 'No district number'
								print repr(line)

					# if the line matches the candidate pattern
					elif cand_match != None:

						# append a candidate to the race's list
						race.candidates.append(
							Race_Candidate(
								  raw_name = cand_match.group(1).replace(u'\xad', '-').strip()
								, party = get_party(cand_match.group(2).strip())
								, votes = cand_match.group(3).strip().replace(',', '')
								, pct_votes = cand_match.group(4).replace('%', '').strip()
							)
						)

					# if the phrase 'Total Votes' is in the line
					elif 'Total Votes' in line:
						# search the current line for the total votes number
						try:
							race.total_votes = re.search('[\d|,]+', line).group().replace(',', '')						
						# if not founnd, try the next line
						except AttributeError:						
							race.total_votes = re.search('[\d|,]+', reader[idx + 1]).group().replace(',', '')
						
						
						# after getting the total votes, append the race to the election's list 
						election.races.append(race)

		elections.append(election)

		print '=============='

for election in elections:

	try:
		with db.atomic():
			election.save()
	except Exception as e:
		if 'duplicate' in e.message:
			pass
		else:
			print 'Error on line #{0}: {1}'.format(inspect.currentframe().f_lineno, e)

	for race in election.races:
		# for now, ignore judicial races, propositions and constitutional amendments
		if race.race_type.name not in [
			  'Constitutional Amendment'
			, 'Proposition'
			, 'Court of Appeals'
			, 'Missouri Supreme Court'
			, 'Circuit Judge'
			, 'Assoc. Circuit Judge'
			, 'U.S. President And Vice President'
		]:
			race.election = election.id

			print '  {}, District # {}'.format(election.election_date, race.district)

			try:
				with db.atomic():
					race.save()
			except Exception as e:
				if 'duplicate' in e.message:
					pass
				else:
					print 'Error on line #{0}: {1}'.format(inspect.currentframe().f_lineno, e)

			for candidate in race.candidates:

				candidate.race = race.id

				raw_name = candidate.raw_name

				parsed_name = parse_name(candidate.raw_name.replace(',,', ','))['name_dict']

				# set the person attribute
				candidate.person = get_or_create_person(parsed_name)['person']
				
				for k, v in candidate._data.iteritems():
					print '   {0}: {1}'.format(k, repr(v))

				# now save
				try:
					with db.atomic():
						candidate.save()
				except Exception as e:
					if 'duplicate' in e.message:
						pass
					else:
						print 'Error on line #{0}: {1}'.format(inspect.currentframe().f_lineno, e)

				print '------'

			print '==================='

print 'fin.'

