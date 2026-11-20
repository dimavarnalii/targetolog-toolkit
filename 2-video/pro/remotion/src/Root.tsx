import React from 'react';
import {Composition} from 'remotion';
import {Creative, creativeDefaults} from './Creative';

// Розмір, fps і тривалість беруться з props, які готує to_remotion.py
const fromProps = ({props}: {props: any}) => ({
	durationInFrames: props.durationInFrames,
	fps: props.fps,
	width: props.width,
	height: props.height,
});

export const Root: React.FC = () => (
	<>
		<Composition
			id="Creative"
			component={Creative as any}
			defaultProps={creativeDefaults}
			durationInFrames={250}
			fps={25}
			width={1080}
			height={1920}
			calculateMetadata={fromProps}
		/>
	</>
);
