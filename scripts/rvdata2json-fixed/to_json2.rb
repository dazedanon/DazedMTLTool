# encoding: utf-8
# to_json2.rb
# author: dice2000
# original author: aoitaku
# https://gist.github.com/aoitaku/7822424
#

require 'jsonable'
require 'zlib'
require_relative 'rgss3'
[
  'Data/Actors.rvdata2',
  'Data/Animations.rvdata2',
#  'Data/Areas.rvdata2',
  'Data/Armors.rvdata2',
  'Data/Classes.rvdata2',
  'Data/CommonEvents.rvdata2',
  'Data/Enemies.rvdata2',
  'Data/Items.rvdata2',
  *Dir.glob('Data/Map[0-9][0-9][0-9].rvdata2'),
  'Data/MapInfos.rvdata2',
  'Data/Skills.rvdata2',
  'Data/States.rvdata2',
  'Data/System.rvdata2',
  'Data/Tilesets.rvdata2',
  'Data/Troops.rvdata2',
  'Data/Weapons.rvdata2'
].each do |rvdata|
  data = ''
  p rvdata
  File.open(rvdata, 'rb') do |file|
    data = Marshal.load(file.read)
    if data.is_a?(Array)
	    data.each{ |d|
	    	d.unpack_names if d != nil
	    }
		elsif data.is_a?(Hash)
			if data.size != 0
				data.each_value{|v|
					v.unpack_names
				}
			end
		else
			data.unpack_names
    end
  end
  File.open('Data/'+File.basename(rvdata,'.rvdata2')+'.json', 'w') do |file|
    file.write(data.to_json)
  end
end

